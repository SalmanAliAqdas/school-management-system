from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from audit.services import record_event

from .models import Copy, Fine, Loan, Membership, Reservation


def require(actor):
    if not actor.is_active or not actor.has_perm("library.manage_library"):
        raise PermissionDenied


@transaction.atomic
def issue(actor, copy_id, membership_id):
    require(actor)
    copy = Copy.objects.select_for_update().get(pk=copy_id)
    membership = (
        Membership.objects.select_for_update().select_related("policy").get(pk=membership_id)
    )
    if copy.status != "available" or not membership.is_active:
        raise ValidationError("This copy or membership is not available.")
    if membership.loans.filter(state="issued").count() >= membership.policy.limit:
        raise ValidationError("Borrowing limit reached.")
    now = timezone.now()
    loan = Loan.objects.create(
        copy=copy,
        membership=membership,
        issued_at=now,
        due_at=now + timedelta(days=membership.policy.loan_days),
        issued_by=actor,
    )
    copy.status = "issued"
    copy.save(update_fields=["status", "updated_at"])
    record_event("library.issued", actor=actor, target=loan.pk)
    return loan


@transaction.atomic
def return_copy(actor, loan_id, *, condition="good"):
    require(actor)
    loan = (
        Loan.objects.select_for_update()
        .select_related("copy", "membership__policy")
        .get(pk=loan_id)
    )
    if loan.state != "issued":
        raise ValidationError("This loan is already closed.")
    now = timezone.now()
    loan.returned_at, loan.returned_by = now, actor
    loan.state = "damaged" if condition == "damaged" else "returned"
    loan.save()
    loan.copy.condition = condition
    loan.copy.status = "repair" if condition == "damaged" else "available"
    loan.copy.save()
    overdue = max(0, (now.date() - loan.due_at.date()).days - loan.membership.policy.grace_days)
    if overdue and loan.membership.policy.daily_fine:
        value = Decimal(overdue) * loan.membership.policy.daily_fine
        cap = loan.membership.policy.fine_cap
        Fine.objects.create(loan=loan, amount=min(value, cap) if cap else value, kind="overdue")
    reservation = (
        Reservation.objects.select_for_update()
        .filter(book=loan.copy.book, state="queued")
        .order_by("created_at")
        .first()
    )
    if reservation:
        reservation.state, loan.copy.status = "available", "reserved"
        reservation.save(update_fields=["state", "updated_at"])
        loan.copy.save(update_fields=["status", "updated_at"])
    record_event("library.returned", actor=actor, target=loan.pk)
    return loan


@transaction.atomic
def renew(actor, loan_id):
    require(actor)
    loan = (
        Loan.objects.select_for_update()
        .select_related("membership__policy", "copy")
        .get(pk=loan_id)
    )
    if (
        loan.state != "issued"
        or loan.renewals >= loan.membership.policy.renewal_limit
        or Reservation.objects.filter(
            book=loan.copy.book, state__in=["queued", "available"]
        ).exists()
    ):
        raise ValidationError("This loan cannot be renewed.")
    loan.due_at += timedelta(days=loan.membership.policy.loan_days)
    loan.renewals += 1
    loan.save()
    return loan


@transaction.atomic
def reserve(member, book):
    if not member.is_active:
        raise ValidationError("Membership is inactive.")
    row, _ = Reservation.objects.get_or_create(book=book, membership=member, state="queued")
    return row
