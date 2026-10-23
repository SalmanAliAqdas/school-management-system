"""Explicit, idempotent late fees. Collection does not silently add penalties."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum

from .common import ZERO, control, event, locked_config, require, rounded, school_day
from .ledger import _post, period_for
from .models import Invoice, InvoiceAdjustment, LateFeeExemption
from .payments import target_balance


@transaction.atomic
def apply_late_fee(actor, invoice_id, *, day=None):
    require(actor, "request_adjustments")
    settings = locked_config()
    day = day or school_day()
    period_for(day)
    invoice = Invoice.objects.get(pk=invoice_id)
    if invoice.state != "issued" or settings.fine_mode == "none" or not settings.fine_value:
        raise ValidationError("Enable a fine policy and choose an issued invoice.")
    eligible_on = invoice.due_on + timedelta(days=settings.fine_grace_days + 1)
    if (
        day < eligible_on
        or day > school_day()
        or (school_day() - day).days > settings.backdate_days
    ):
        raise ValidationError("This fine date is outside the policy or allowed posting window.")
    bucket = (
        (day - eligible_on).days // settings.fine_repeat_days if settings.fine_repeat_days else 0
    )
    key = f"fine:{invoice.pk}:{bucket}"
    previous = InvoiceAdjustment.objects.filter(source_key=key).first()
    if previous:
        return previous
    if LateFeeExemption.objects.filter(
        student=invoice.student, starts_on__lte=day, ends_on__gte=day, request__state="approved"
    ).exists():
        raise ValidationError("This student invoice is exempt from late fees.")
    base = sum(
        (
            max(ZERO, target_balance(line=line))
            for line in invoice.lines.all()
            if line.details["late_fee_eligible"]
            and line.details["treatment"] not in ("deposit", "opening")
        ),
        ZERO,
    )
    value = (
        rounded(
            settings.fine_value
            if settings.fine_mode == "fixed"
            else base * settings.fine_value / 100,
            settings,
        )
        if base
        else ZERO
    )
    previous_total = invoice.adjustments.filter(kind="fine").aggregate(v=Sum("amount"))["v"] or ZERO
    if settings.fine_cap:
        value = min(value, max(ZERO, settings.fine_cap - previous_total))
    if not value:
        raise ValidationError("No eligible unpaid fee remains or the fine cap was reached.")
    row = InvoiceAdjustment.objects.create(
        invoice=invoice,
        kind="fine",
        amount=value,
        occurred_on=day,
        reason="Explicit application of configured late fee policy",
        source_key=key,
        details={
            "base": str(base),
            "mode": settings.fine_mode,
            "value": str(settings.fine_value),
            "bucket": bucket,
        },
    )
    _post(
        actor,
        settings,
        source_key=key,
        source_type="fine",
        source_id=row.pk,
        day=day,
        memo=row.reason,
        lines=[
            (control("receivable"), invoice.student, value, ZERO),
            (control("fine"), None, ZERO, value),
        ],
    )
    event(actor, "fine_applied", row.pk, student=invoice.student)
    return row
