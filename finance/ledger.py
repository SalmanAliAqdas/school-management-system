"""Internal journal writer; owning public services perform action/object approval checks."""

from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.db.models import Sum

from .common import ZERO, amount, capable, school_day
from .models import FinancialPeriod, JournalEntry, JournalLine


def period_for(day, *, allow_closed=False):
    period = (
        FinancialPeriod.objects.select_related("financial_year")
        .filter(starts_on__lte=day, ends_on__gte=day)
        .first()
    )
    if not period or (not allow_closed and (period.is_closed or period.financial_year.is_closed)):
        raise ValidationError("Choose a date in an open financial period and year.")
    return period


def _post(
    actor,
    settings,
    *,
    source_key,
    source_type,
    source_id,
    day,
    memo,
    lines,
    request=None,
    reversal_of=None,
):
    if not capable(actor, "view_all_finance") or not any(
        capable(actor, p)
        for p in (
            "collect_payments",
            "generate_invoices",
            "allocate_credit",
            "approve_finance",
            "record_expenses",
        )
    ):
        raise PermissionDenied
    if not connection.in_atomic_block:
        raise RuntimeError("Journal posting requires the serialized atomic finance workflow.")
    existing = JournalEntry.objects.filter(source_key=source_key).first()
    if existing:
        return existing
    if day > school_day():
        raise ValidationError("Future-dated monetary postings are not allowed.")
    period = period_for(day)
    if request and (
        request.state != "approved" or request.reviewed_by_id == request.requested_by_id
    ):
        raise ValidationError("This posting requires a completed independent approval.")
    prepared = []
    for account, student, debit, credit in lines:
        debit = amount(debit, settings, positive=False)
        credit = amount(credit, settings, positive=False)
        if not debit and not credit:
            continue
        if not account.is_active or bool(debit) == bool(credit):
            raise ValidationError(
                "Each journal line requires one active account and exactly one positive side."
            )
        if account.control in ("receivable", "advance", "deposit", "deposit_due") and not student:
            raise ValidationError("Student control accounts require a student identity.")
        prepared.append((account, student, debit, credit))
    if not prepared:
        return None  # A fully waived deferred document has no economic posting.
    if sum((r[2] for r in prepared), ZERO) != sum((r[3] for r in prepared), ZERO):
        raise ValidationError("The financial posting does not balance; no records were posted.")
    entry = JournalEntry.objects.create(
        source_key=source_key,
        source_type=source_type,
        source_id=str(source_id),
        occurred_on=day,
        period=period,
        currency=settings.currency,
        memo=memo[:300],
        actor=actor,
        request=request,
        reversal_of=reversal_of,
    )
    JournalLine.objects.bulk_create(
        [
            JournalLine(journal=entry, account=acc, student=student, debit=debit, credit=credit)
            for acc, student, debit, credit in prepared
        ]
    )
    entry.state = "posted"
    entry.save(update_fields=["state", "updated_at"])
    return entry


def net_balance(*, account=None, control=None, student=None, through=None, before=None):
    rows = JournalLine.objects.filter(journal__state="posted")
    if account:
        rows = rows.filter(account=account)
    if control:
        rows = rows.filter(account__control=control)
    if student:
        rows = rows.filter(student=student)
    if through:
        rows = rows.filter(journal__occurred_on__lte=through)
    if before:
        rows = rows.filter(journal__occurred_on__lt=before)
    totals = rows.aggregate(debit=Sum("debit"), credit=Sum("credit"))
    return (totals["debit"] or ZERO) - (totals["credit"] or ZERO)


def student_balances(student, *, through=None):
    return {
        "owed": net_balance(control="receivable", student=student, through=through),
        "advance": -net_balance(control="advance", student=student, through=through),
        "deposit": -net_balance(control="deposit", student=student, through=through),
        "deposit_due": -net_balance(control="deposit_due", student=student, through=through),
    }


def trial_balance(*, through=None, start=None):
    rows = JournalLine.objects.filter(journal__state="posted")
    if through:
        rows = rows.filter(journal__occurred_on__lte=through)
    if start:
        rows = rows.filter(journal__occurred_on__gte=start)
    return list(
        rows.values(
            "account_id", "account__code", "account__name", "account__kind", "account__control"
        )
        .annotate(debit=Sum("debit"), credit=Sum("credit"))
        .order_by("account__code")
    )


def assert_consistent():
    bad = []
    for row in JournalEntry.objects.filter(state="posted").annotate(
        debits=Sum("lines__debit"), credits=Sum("lines__credit")
    ):
        if row.debits is None or row.debits != row.credits:
            bad.append(str(row.pk))
    if bad:
        raise ValidationError(f"Unbalanced journal entries: {', '.join(bad[:10])}")
    totals = trial_balance()
    if sum((r["debit"] for r in totals), Decimal(0)) != sum(
        (r["credit"] for r in totals), Decimal(0)
    ):
        raise ValidationError("The trial balance does not balance.")
    from people.models import Student

    from .models import Allocation, Invoice
    from .payments import active_allocations, allocation_remaining, invoice_totals, lot_available

    for student in Student.objects.filter(journalline__isnull=False).distinct():
        invoices = Invoice.objects.filter(student=student, state="issued")
        owed = sum((invoice_totals(invoice)["balance"] for invoice in invoices), ZERO)
        advance = sum(
            (lot_available(lot, reservations=False) for lot in student.credit_lots.all()), ZERO
        )
        deposit = ZERO
        deposit_due = ZERO
        for invoice in invoices:
            for line in invoice.lines.filter(details__treatment="deposit"):
                credits = line.adjustments.aggregate(total=Sum("amount"))["total"] or ZERO
                deposit_due += line.net + credits - active_allocations(line=line)
        for allocation in Allocation.objects.filter(
            credit__student=student, line__details__treatment="deposit"
        ):
            deposit += allocation_remaining(allocation) - (
                allocation.deposit_refunds.aggregate(total=Sum("amount"))["total"] or ZERO
            )
        expected = {
            "owed": owed,
            "advance": advance,
            "deposit": deposit,
            "deposit_due": deposit_due,
        }
        actual = student_balances(student)
        if actual != expected or any(value < 0 for value in actual.values()):
            raise ValidationError(
                f"Student control balances disagree with permanent documents: {student.pk}"
            )
    return {"posted_entries": JournalEntry.objects.filter(state="posted").count(), "balanced": True}
