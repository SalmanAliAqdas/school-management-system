from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from audit.services import record_event

from .models import Asset, AssetEvent, Item, StockMovement


def balance(item, location):
    received = StockMovement.objects.filter(
        item=item, to_location=location, state="finalized"
    ).aggregate(v=Sum("quantity"))["v"] or Decimal("0")
    issued = StockMovement.objects.filter(
        item=item, from_location=location, state="finalized"
    ).aggregate(v=Sum("quantity"))["v"] or Decimal("0")
    return received - issued


@transaction.atomic
def finalize(actor, movement_id):
    if not actor.is_active or not actor.has_perm("inventory.manage_inventory"):
        raise PermissionDenied
    row = StockMovement.objects.select_for_update().select_related("item").get(pk=movement_id)
    Item.objects.select_for_update().get(pk=row.item_id)
    if row.state != "draft":
        raise ValidationError("Only draft movements can be finalized.")
    if row.kind in ("issue", "transfer") and (
        not row.from_location_id or balance(row.item, row.from_location) < abs(row.quantity)
    ):
        raise ValidationError("Insufficient stock for this movement.")
    if row.kind in ("receipt", "opening", "return") and not row.to_location_id:
        raise ValidationError("A receiving location is required.")
    if row.kind == "transfer" and (
        not row.to_location_id or row.to_location_id == row.from_location_id
    ):
        raise ValidationError("A transfer requires different locations.")
    if row.kind == "adjustment" and not actor.has_perm("inventory.approve_inventory"):
        raise PermissionDenied
    row.quantity = abs(row.quantity)
    row.state = "finalized"
    row.save()
    record_event("inventory.finalized", actor=actor, target=row.pk)
    return row


@transaction.atomic
def reverse(actor, movement_id, reference, reason):
    """Correct a finalized stock event using an equal compensating movement."""
    if not actor.is_active or not actor.has_perm("inventory.approve_inventory"):
        raise PermissionDenied
    original = StockMovement.objects.select_for_update().get(pk=movement_id)
    Item.objects.select_for_update().get(pk=original.item_id)
    if original.state != "finalized" or hasattr(original, "reversal") or not reason.strip():
        raise ValidationError("Only a finalized movement can be corrected with a reason.")
    correction = StockMovement.objects.create(
        reference=reference,
        item=original.item,
        kind="correction",
        quantity=original.quantity,
        from_location=original.to_location,
        to_location=original.from_location,
        occurred_on=original.occurred_on,
        reason=reason,
        actor=actor,
        reverses=original,
    )
    if (
        correction.from_location_id
        and balance(original.item, correction.from_location) < original.quantity
    ):
        raise ValidationError("The correction would make stock negative.")
    correction.state = "finalized"
    correction.save(update_fields=["state", "updated_at"])
    record_event("inventory.reversed", actor=actor, target=correction.pk)
    return correction


@transaction.atomic
def request_disposal(actor, asset_id, reason):
    if not actor.is_active or not actor.has_perm("inventory.manage_inventory"):
        raise PermissionDenied
    asset = Asset.objects.select_for_update().get(pk=asset_id)
    if asset.status == "disposed" or not reason.strip():
        raise ValidationError("An active asset and disposal reason are required.")
    if asset.events.filter(kind="disposal_requested", approved_by=None).exists():
        raise ValidationError("A disposal request is already pending.")
    return AssetEvent.objects.create(
        asset=asset,
        kind="disposal_requested",
        occurred_on=timezone.localdate(),
        details=reason,
        actor=actor,
    )


@transaction.atomic
def approve_disposal(actor, event_id):
    if not actor.is_active or not actor.has_perm("inventory.approve_inventory"):
        raise PermissionDenied
    event = AssetEvent.objects.select_for_update().select_related("asset").get(pk=event_id)
    if event.kind != "disposal_requested" or event.approved_by_id:
        raise ValidationError("Only a pending disposal request can be approved.")
    if event.actor_id == actor.pk:
        raise ValidationError("Asset disposal requires an independent approver.")
    event.approved_by = actor
    event.save(update_fields=["approved_by", "updated_at"])
    event.asset.status = "disposed"
    event.asset.save(update_fields=["status", "updated_at"])
    AssetEvent.objects.create(
        asset=event.asset,
        kind="disposed",
        occurred_on=timezone.localdate(),
        details=event.details,
        actor=event.actor,
        approved_by=actor,
    )
    record_event("inventory.asset_disposed", actor=actor, target=event.asset_id)
    return event.asset
