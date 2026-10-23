from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from .common import ZERO, amount, control, event, locked_config, require, school_day
from .ledger import _post, net_balance, period_for, trial_balance
from .models import (
    Expense,
    ExpensePayment,
    FinancialPeriod,
    FinancialRequest,
    FinancialYear,
    JournalLine,
    PeriodEvent,
    Reconciliation,
    ReconciliationLine,
)


def validate_reconciliation(account, payload, *, request=None):
    if account.control not in ("cash", "bank") or not account.is_active:
        raise ValidationError("Reconcile an active cash or bank account.")
    start, end = date.fromisoformat(payload["starts_on"]), date.fromisoformat(payload["ends_on"])
    if start > end or end > school_day():
        raise ValidationError("Choose a valid historical statement date range.")
    previous = (
        Reconciliation.objects.filter(account=account, request__state="approved")
        .order_by("-ends_on")
        .first()
    )
    if previous and start <= previous.ends_on:
        raise ValidationError("Statements must follow the previously approved statement.")
    expected = (
        previous.closing_statement if previous else net_balance(account=account, before=start)
    )
    if Decimal(payload["opening"]) != expected:
        raise ValidationError(
            "Statement opening must match the last approved closing or first book opening."
        )
    ids = payload.get("lines", [])
    rows = JournalLine.objects.filter(
        pk__in=ids, account=account, journal__state="posted", journal__occurred_on__lte=end
    )
    if len(set(map(str, ids))) != len(ids) or rows.count() != len(ids):
        raise ValidationError(
            "Select distinct posted transactions belonging to this account and statement date."
        )
    active = ReconciliationLine.objects.filter(line_id__in=ids, is_active=True)
    if request:
        active = active.exclude(reconciliation__request=request)
    if active.exists():
        raise ValidationError("A selected transaction is already reconciled or reserved.")
    delta = sum((row.debit - row.credit for row in rows), ZERO)
    if expected + delta != Decimal(payload["closing"]):
        raise ValidationError(
            "The statement closing must equal opening plus the selected transactions."
        )
    return rows


@transaction.atomic
def request_reconciliation(actor, account, payload, reason):
    require(actor, "reconcile_accounts")
    settings = locked_config()
    payload = dict(payload)
    payload["opening"] = str(amount(payload["opening"], settings, positive=False, signed=True))
    payload["closing"] = str(amount(payload["closing"], settings, positive=False, signed=True))
    rows = list(validate_reconciliation(account, payload))
    from .approvals import request_action

    request = request_action(
        actor,
        "reconcile",
        day=date.fromisoformat(payload["ends_on"]),
        reason=reason,
        target_account=account,
        payload=payload,
    )
    reconciliation = Reconciliation.objects.create(
        request=request,
        account=account,
        starts_on=payload["starts_on"],
        ends_on=payload["ends_on"],
        opening_statement=payload["opening"],
        closing_statement=payload["closing"],
    )
    ReconciliationLine.objects.bulk_create(
        [ReconciliationLine(reconciliation=reconciliation, line=row) for row in rows]
    )
    return request


def approve_reconciliation(request):
    # Rows were reserved when requested, and checked again under the common finance lock.
    if not hasattr(request, "reconciliation"):
        raise ValidationError("Use the reconciliation workflow to reserve selected transactions.")


def change_period(request):
    closing = request.kind.startswith("close")
    if request.period_id:
        periods = FinancialPeriod.objects.filter(pk=request.period_id)
        target = request.period
        if not closing and target.financial_year.is_closed:
            raise ValidationError("Reopen the financial year before its period.")
    else:
        target = FinancialYear.objects.get(pk=request.payload["year"])
        periods = target.periods.all()
    if closing:
        start, end = target.starts_on, target.ends_on
        if end > school_day():
            raise ValidationError("A financial period cannot close before its end date.")
        if (
            FinancialRequest.objects.filter(state="pending", occurred_on__range=(start, end))
            .exclude(pk=request.pk)
            .exists()
        ):
            raise ValidationError("Resolve pending financial decisions before closing this period.")
        rows = JournalLine.objects.filter(
            journal__period__in=periods, account__control__in=["cash", "bank"]
        )
        cleared = ReconciliationLine.objects.filter(
            line__in=rows, is_active=True, reconciliation__request__state="approved"
        ).values_list("line_id", flat=True)
        if rows.exclude(pk__in=cleared).exists():
            raise ValidationError("Reconcile every cash and bank transaction before closing.")
        if not request.period_id and periods.filter(is_closed=False).exists():
            raise ValidationError("Close all financial periods before closing their year.")
    target.is_closed = closing
    target.save(update_fields=["is_closed", "updated_at"])
    PeriodEvent.objects.create(
        request=request,
        snapshot={
            "closed": closing,
            "through": target.ends_on.isoformat(),
            "trial_balance": [
                {k: str(v) for k, v in row.items()} for row in trial_balance(through=target.ends_on)
            ],
        },
    )


@transaction.atomic
def request_expense(actor, *, category, day, payee, value, description, attachment=None):
    require(actor, "record_expenses")
    settings = locked_config()
    value = amount(value, settings)
    period_for(day)
    if category.account.kind != "expense" or not category.account.is_active:
        raise ValidationError("Choose an active expense account.")
    from core.uploads import image_write, sanitize_image

    expense = Expense(
        category=category,
        occurred_on=day,
        payee=payee.strip(),
        amount=value,
        description=description.strip(),
        created_by=actor,
    )
    if attachment:
        expense.attachment = sanitize_image(attachment)
    expense.full_clean()
    with image_write(expense, "attachment"):
        expense.save()
        from .approvals import request_action

        request = request_action(
            actor,
            "expense",
            amount_value=value,
            day=day,
            reason=description,
            payload={"expense": str(expense.pk)},
        )
        expense.request = request
        expense.save(update_fields=["request", "updated_at"])
    return expense


@transaction.atomic
def pay_expense(actor, expense_id, account, day, reference):
    require(actor, "record_expenses")
    settings = locked_config()
    expense = Expense.objects.select_related("request").get(pk=expense_id)
    if expense.request.state != "approved" or hasattr(expense, "payment"):
        raise ValidationError("Only an approved unpaid expense can be paid once.")
    if (
        account.control not in ("cash", "bank")
        or not account.is_active
        or day < expense.occurred_on
    ):
        raise ValidationError(
            "Choose an active cash/bank account and date on or after the expense."
        )
    if (school_day() - day).days > settings.backdate_days:
        raise ValidationError("Expense disbursements must be within the permitted posting window.")
    payment = ExpensePayment.objects.create(
        expense=expense, account=account, paid_on=day, reference=reference.strip(), paid_by=actor
    )
    payment.full_clean()
    _post(
        actor,
        settings,
        source_key=f"expense_payment:{payment.pk}",
        source_type="expense_payment",
        source_id=payment.pk,
        day=day,
        memo=expense.description,
        request=expense.request,
        lines=[
            (control("payable"), None, expense.amount, ZERO),
            (account, None, ZERO, expense.amount),
        ],
    )
    event(actor, "expense_paid", expense.pk)
    return payment
