from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Sum

from .common import (
    ZERO,
    amount,
    control,
    event,
    fingerprint,
    locked_config,
    next_number,
    require,
    school_day,
    school_snapshot,
)
from .ledger import _post, period_for, student_balances
from .models import Allocation, AllocationRelease, CreditLot, FinancialRequest, Invoice, Payment


def active_allocations(*, invoice=None, line=None, charge=None, credit=None, through=None):
    rows = Allocation.objects.all()
    for name, value in (
        ("invoice", invoice),
        ("line", line),
        ("charge", charge),
        ("credit", credit),
    ):
        if value is not None:
            rows = rows.filter(**{name: value})
    if through:
        rows = rows.filter(allocated_on__lte=through)
    released = AllocationRelease.objects.filter(allocation__in=rows)
    if through:
        released = released.filter(request__occurred_on__lte=through)
    return (rows.aggregate(total=Sum("amount"))["total"] or ZERO) - (
        released.aggregate(total=Sum("amount"))["total"] or ZERO
    )


def allocation_remaining(allocation):
    return allocation.amount - (allocation.releases.aggregate(total=Sum("amount"))["total"] or ZERO)


def reversal_for(payment, *, exclude=None):
    rows = FinancialRequest.objects.filter(
        kind="reverse_payment", payment=payment, state="approved"
    )
    if exclude:
        rows = rows.exclude(pk=exclude.pk)
    return rows.first()


def lot_available(lot, *, reservations=True, exclude_request=None):
    if lot.payment_id and reversal_for(lot.payment, exclude=exclude_request):
        return ZERO
    value = (
        lot.amount
        - active_allocations(credit=lot)
        - (lot.refunds.aggregate(total=Sum("amount"))["total"] or ZERO)
    )
    if reservations:
        requests = FinancialRequest.objects.filter(
            credit=lot, kind="refund_credit", state="pending"
        )
        if exclude_request:
            requests = requests.exclude(pk=exclude_request.pk)
        value -= requests.aggregate(total=Sum("amount"))["total"] or ZERO
        if (
            lot.payment_id
            and FinancialRequest.objects.filter(
                kind="reverse_payment", payment_id=lot.payment_id, state="pending"
            )
            .exclude(pk=exclude_request.pk if exclude_request else None)
            .exists()
        ):
            return ZERO
    if value < 0:
        raise ValidationError(
            "This credit lot is inconsistent; investigate permanent postings before continuing."
        )
    return value


def target_balance(*, line=None, charge=None):
    if line:
        credited = (
            line.adjustments.filter(amount__lt=0).aggregate(total=Sum("amount"))["total"] or ZERO
        )
        return line.net + credited - active_allocations(line=line)
    credited = charge.credits.aggregate(total=Sum("amount"))["total"] or ZERO
    return charge.amount + credited - active_allocations(charge=charge)


def invoice_totals(invoice, *, through=None):
    adjustments = invoice.adjustments.all()
    if through:
        adjustments = adjustments.filter(occurred_on__lte=through)
    adjustment = adjustments.aggregate(total=Sum("amount"))["total"] or ZERO
    applied = active_allocations(invoice=invoice, through=through)
    return _invoice_totals(invoice, adjustment, applied, through=through)


def _invoice_totals(invoice, adjustment, applied, *, through=None, reference_day=None):
    total = invoice.total + adjustment
    outstanding = total - applied
    voided = invoice.state == "voided"
    if voided and through:
        voided = FinancialRequest.objects.filter(
            invoice=invoice, kind="void", state="approved", occurred_on__lte=through
        ).exists()
    if voided:
        total = outstanding = ZERO
    if outstanding < 0 or total < 0:
        raise ValidationError(
            "Invoice allocations/adjustments are inconsistent; ordinary posting is blocked."
        )
    state = "voided" if voided else "issued" if invoice.state == "voided" else invoice.state
    if state == "issued":
        state = (
            "paid"
            if outstanding == 0
            else "overdue"
            if invoice.due_on < (through or reference_day or school_day())
            else "partially_paid"
            if applied > 0
            else "issued"
        )
    return {
        "original": invoice.total,
        "adjustments": adjustment,
        "effective": total,
        "allocated": applied,
        "balance": outstanding,
        "status": state,
    }


def invoice_total_map(invoices):
    """Batch current totals using the same allocations/releases and status rules."""
    from .models import InvoiceAdjustment

    invoices = list(invoices)
    ids = [invoice.pk for invoice in invoices]
    adjustments = dict(
        InvoiceAdjustment.objects.filter(invoice_id__in=ids)
        .values("invoice_id")
        .annotate(total=Sum("amount"))
        .values_list("invoice_id", "total")
    )
    allocations = dict(
        Allocation.objects.filter(invoice_id__in=ids)
        .values("invoice_id")
        .annotate(total=Sum("amount"))
        .values_list("invoice_id", "total")
    )
    releases = dict(
        AllocationRelease.objects.filter(allocation__invoice_id__in=ids)
        .values("allocation__invoice_id")
        .annotate(total=Sum("amount"))
        .values_list("allocation__invoice_id", "total")
    )
    today = school_day()
    return {
        invoice.pk: _invoice_totals(
            invoice,
            adjustments.get(invoice.pk, ZERO),
            allocations.get(invoice.pk, ZERO) - releases.get(invoice.pk, ZERO),
            reference_day=today,
        )
        for invoice in invoices
    }


def deposit_available(allocation, *, exclude_request=None):
    if not allocation.line_id or allocation.line.details["treatment"] != "deposit":
        raise ValidationError("Choose a funded refundable-deposit allocation.")
    available = allocation_remaining(allocation) - (
        allocation.deposit_refunds.aggregate(total=Sum("amount"))["total"] or ZERO
    )
    pending = FinancialRequest.objects.filter(
        kind="refund_deposit", allocation=allocation, state="pending"
    )
    if exclude_request:
        pending = pending.exclude(pk=exclude_request.pk)
    return available - (pending.aggregate(total=Sum("amount"))["total"] or ZERO)


def _allocate(actor, settings, lot, invoice, value, day, source_key, *, request=None):
    if invoice.student_id != lot.student_id or invoice.state != "issued":
        raise ValidationError("Allocate only to this student's issued, non-void invoice.")
    value = amount(value, settings)
    if day < invoice.issue_on or (lot.payment_id and day < lot.payment.paid_on):
        raise ValidationError("Allocation dates cannot precede the invoice or original payment.")
    existing = Allocation.objects.filter(source_key__startswith=source_key + ":").exists()
    if existing:
        raise ValidationError("This allocation action was already processed; reload the account.")
    if (
        value > lot_available(lot, exclude_request=request)
        or value > invoice_totals(invoice)["balance"]
    ):
        raise ValidationError(
            "Allocation exceeds available credit or the invoice's outstanding balance."
        )
    remaining = value
    targets = [(line, None) for line in invoice.lines.select_related("category").order_by("pk")] + [
        (None, charge)
        for charge in invoice.adjustments.filter(amount__gt=0).order_by("created_at", "pk")
    ]
    created = []
    for index, (line, charge) in enumerate(targets):
        balance = target_balance(line=line, charge=charge)
        value_for_target = min(remaining, balance)
        if value_for_target <= 0:
            continue
        allocation = Allocation.objects.create(
            credit=lot,
            invoice=invoice,
            line=line,
            charge=charge,
            amount=value_for_target,
            allocated_on=day,
            source_key=f"{source_key}:{index}",
        )
        postings = [
            (control("advance"), lot.student, value_for_target, ZERO),
            (control("receivable"), lot.student, ZERO, value_for_target),
        ]
        if line and line.details["treatment"] == "deposit":
            postings.extend(
                [
                    (control("deposit_due"), lot.student, value_for_target, ZERO),
                    (control("deposit"), lot.student, ZERO, value_for_target),
                ]
            )
        _post(
            actor,
            settings,
            source_key=f"allocation:{allocation.pk}",
            source_type="allocation",
            source_id=allocation.pk,
            day=day,
            memo=f"Allocation to {invoice.number}",
            lines=postings,
            request=request,
        )
        created.append(allocation)
        remaining -= value_for_target
        if not remaining:
            break
    if remaining:
        raise ValidationError("Invoice item balances did not match its outstanding total.")
    return created


@transaction.atomic
def allocate_credit(actor, credit_id, invoice_id, value, day, *, idempotency_key):
    require(actor, "allocate_credit")
    settings = locked_config()
    lot = (
        CreditLot.objects.select_for_update(of=("self",))
        .select_related("student", "payment")
        .get(pk=credit_id)
    )
    invoice = Invoice.objects.select_for_update(of=("self",)).get(pk=invoice_id)
    if (school_day() - day).days > settings.backdate_days:
        from .approvals import request_action

        return request_action(
            actor,
            "allocate",
            amount_value=value,
            day=day,
            reason="Backdated student credit allocation",
            credit=lot,
            invoice=invoice,
            payload={"key": str(idempotency_key)},
        )
    result = _allocate(actor, settings, lot, invoice, value, day, f"manual:{idempotency_key}")
    event(actor, "credit_allocated", invoice.pk, student=lot.student)
    return result


def _release(actor, settings, allocation, value, request, *, suffix=""):
    value = amount(value, settings)
    if value > allocation_remaining(allocation):
        raise ValidationError("A release cannot exceed its original active allocation.")
    if (
        allocation.deposit_refunds.exists()
        or FinancialRequest.objects.filter(
            kind="refund_deposit", allocation=allocation, state="pending"
        )
        .exclude(pk=request.pk)
        .exists()
    ):
        raise ValidationError(
            "Deposit refunds or reservations protect this allocation from reversal."
        )
    for pending in FinancialRequest.objects.filter(kind="refund_fee", state="pending").exclude(
        pk=request.pk
    ):
        if any(
            str(allocation.pk) == fund["allocation"] for fund in pending.payload.get("funding", [])
        ):
            raise ValidationError("An approved/refunding workflow has reserved this allocation.")
    row = AllocationRelease.objects.create(
        allocation=allocation,
        request=request,
        amount=value,
        source_key=f"release:{request.pk}:{allocation.pk}:{suffix}",
    )
    postings = [
        (control("receivable"), allocation.credit.student, value, ZERO),
        (control("advance"), allocation.credit.student, ZERO, value),
    ]
    if allocation.line_id and allocation.line.details["treatment"] == "deposit":
        postings.extend(
            [
                (control("deposit"), allocation.credit.student, value, ZERO),
                (control("deposit_due"), allocation.credit.student, ZERO, value),
            ]
        )
    _post(
        actor,
        settings,
        source_key=row.source_key,
        source_type="allocation_release",
        source_id=row.pk,
        day=request.occurred_on,
        memo="Compensating allocation release",
        lines=postings,
        request=request,
    )
    return row


def _post_payment(actor, settings, payment, allocations, *, request=None):
    if payment.state == "posted":
        return payment
    if payment.state != "pending":
        raise ValidationError("Only pending payments can be posted.")
    _post(
        actor,
        settings,
        source_key=f"payment:{payment.pk}",
        source_type="payment",
        source_id=payment.pk,
        day=payment.paid_on,
        memo="Manual school collection",
        lines=[
            (payment.method.account, None, payment.amount, ZERO),
            (control("advance"), payment.student, ZERO, payment.amount),
        ],
        request=request,
    )
    lot = CreditLot.objects.create(student=payment.student, payment=payment, amount=payment.amount)
    settled = []
    for index, intent in enumerate(allocations):
        invoice = Invoice.objects.select_for_update(of=("self",)).get(pk=intent["invoice"])
        _allocate(
            actor,
            settings,
            lot,
            invoice,
            intent["amount"],
            payment.paid_on,
            f"payment:{payment.pk}:{index}",
            request=request,
        )
        settled.append(
            {
                "invoice": invoice.number,
                "amount": str(intent["amount"]),
                "balance": str(invoice_totals(invoice)["balance"]),
            }
        )
    from .common import school_now

    payment.number = next_number("receipt", payment.paid_on, settings)
    payment.posted_by, payment.posted_at = actor, school_now()
    payment.snapshot = {
        "school": school_snapshot(settings),
        "number": payment.number,
        "student": str(payment.student),
        "admission": payment.student.admission_number,
        "amount": str(payment.amount),
        "method": payment.method.name,
        "reference": payment.reference,
        "paid_on": payment.paid_on.isoformat(),
        "issued_at": payment.posted_at.isoformat(),
        "cashier": payment.created_by.display_name,
        "posted_by": actor.display_name,
        "manual": True,
        "allocations": settled,
        "balances": {k: str(v) for k, v in student_balances(payment.student).items()},
    }
    placement = (
        payment.student.enrollments.filter(started_on__lte=payment.paid_on)
        .filter(Q(ended_on__isnull=True) | Q(ended_on__gte=payment.paid_on))
        .select_related("section__school_class")
        .first()
    )
    payment.snapshot["class"] = placement.section.school_class.name if placement else ""
    payment.snapshot["section"] = placement.section.name if placement else ""
    payment.state = "posted"
    payment.save()
    from .notifications import notify

    notify(payment.student, "payment_posted", f"payment:{payment.pk}", payment=payment)
    notify(payment.student, "receipt_available", f"receipt:{payment.pk}", payment=payment)
    event(actor, "payment_posted", payment.pk, student=payment.student)
    return payment


@transaction.atomic
def collect_payment(
    actor, *, student, value, day, method, reference, idempotency_key, allocations=(), notes=""
):
    require(actor, "collect_payments")
    settings = locked_config()
    value = amount(value, settings)
    if (
        not method.is_active
        or not method.account.is_active
        or method.account.control not in ("cash", "bank")
    ):
        raise ValidationError("Choose an active configured manual collection method.")
    if not reference.strip() or len(reference) > 100:
        raise ValidationError("Provide a unique collection slip or manual transaction reference.")
    period_for(day)
    if day > school_day():
        raise ValidationError("A payment date cannot be in the future.")
    allocations = [
        {"invoice": str(row["invoice"]), "amount": str(amount(row["amount"], settings))}
        for row in allocations
    ]
    if (
        len({row["invoice"] for row in allocations}) != len(allocations)
        or sum((amount(row["amount"], settings) for row in allocations), ZERO) > value
    ):
        raise ValidationError("Use distinct invoices and allocate at most the payment amount.")
    digest = fingerprint(
        {
            "student": str(student.pk),
            "amount": str(value),
            "date": day,
            "method": method.pk,
            "reference": reference.strip(),
            "allocations": allocations,
            "notes": notes,
        }
    )
    previous = Payment.objects.filter(idempotency_key=idempotency_key).first()
    if previous:
        if previous.fingerprint != digest:
            raise ValidationError("This payment token was already used with different details.")
        return previous
    if Payment.objects.filter(method=method, reference=reference.strip()).exists():
        raise ValidationError("This manual payment reference is already recorded.")
    payment = Payment.objects.create(
        student=student,
        amount=value,
        paid_on=day,
        method=method,
        reference=reference.strip(),
        idempotency_key=idempotency_key,
        fingerprint=digest,
        created_by=actor,
        notes=notes[:300],
    )
    if (
        value >= settings.payment_approval_threshold
        or (school_day() - day).days > settings.backdate_days
    ):
        from .approvals import request_action

        request_action(
            actor,
            "payment",
            amount_value=value,
            day=day,
            reason="Payment requires configured independent approval",
            payment=payment,
            payload={"allocations": allocations},
        )
        return payment
    return _post_payment(actor, settings, payment, allocations)
