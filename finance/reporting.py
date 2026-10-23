from collections import defaultdict

from django.core.exceptions import ValidationError
from django.db.models import Q, Sum

from .common import ZERO, require, school_day
from .ledger import net_balance, trial_balance
from .models import (
    Expense,
    FinancialRequest,
    Invoice,
    InvoiceLine,
    JournalLine,
    Payment,
    Refund,
)
from .payments import active_allocations, invoice_totals, reversal_for

LIMIT = 5000


def financial_report(actor, *, start=None, end=None, year=None, school_class=None, overdue=False):
    require(actor, "view_finance_reports")
    today = end or school_day()
    rows = (
        Invoice.objects.filter(Q(state="issued") | Q(state="voided"))
        .exclude(
            pk__in=FinancialRequest.objects.filter(
                kind="void", state="approved", occurred_on__lte=today
            ).values("invoice_id"),
        )
        .select_related("student", "academic_year", "cycle")
    )
    if year:
        rows = rows.filter(academic_year=year)
    if start:
        rows = rows.filter(issue_on__gte=start)
    rows = rows.filter(issue_on__lte=today)
    if school_class:
        rows = rows.filter(lines__enrollment__section__school_class=school_class).distinct()
    if rows.count() > LIMIT:
        raise ValidationError("Narrow the report to at most 5,000 invoices.")
    invoices = []
    aging = {key: ZERO for key in ("current", "1-30", "31-60", "61-90", "over 90")}
    classes = defaultdict(lambda: ZERO)
    billed = ZERO
    for invoice in rows.prefetch_related("lines"):
        totals = invoice_totals(invoice, through=today)
        if overdue and (invoice.due_on >= today or not totals["balance"]):
            continue
        billed += totals["effective"]
        invoices.append({"invoice": invoice, **totals})
        days = (today - invoice.due_on).days
        bucket = (
            "current"
            if days <= 0
            else "1-30"
            if days <= 30
            else "31-60"
            if days <= 60
            else "61-90"
            if days <= 90
            else "over 90"
        )
        aging[bucket] += totals["balance"]
        allocated_class_total = ZERO
        lines = list(invoice.lines.all())
        for line in lines:
            credited = (
                line.adjustments.filter(occurred_on__lte=today).aggregate(value=Sum("amount"))[
                    "value"
                ]
                or ZERO
            )
            line_balance = line.net + credited - active_allocations(line=line, through=today)
            classes[line.details["class"]] += line_balance
            allocated_class_total += line_balance
        classes[lines[0].details["class"] if lines else "Unassigned"] += (
            totals["balance"] - allocated_class_total
        )
    payments = Payment.objects.filter(state="posted", paid_on__lte=today)
    if start:
        payments = payments.filter(paid_on__gte=start)
    if year or school_class or overdue:
        payments = payments.filter(student_id__in=[row["invoice"].student_id for row in invoices])
    collections = ZERO
    monthly = defaultdict(lambda: ZERO)
    today_collected = ZERO
    payment_register = []
    daily = defaultdict(lambda: ZERO)
    methods = defaultdict(lambda: ZERO)
    cashiers = defaultdict(lambda: ZERO)
    if payments.count() > LIMIT:
        raise ValidationError("Narrow the collection register to at most 5,000 payments.")
    for payment in payments.select_related("method", "created_by", "student"):
        reverse = reversal_for(payment)
        payment_register.append(
            {
                "payment": payment,
                "status": "reversed" if reverse and reverse.occurred_on <= today else "posted",
            }
        )
        if reverse and reverse.occurred_on <= today:
            continue
        daily[payment.paid_on.isoformat()] += payment.amount
        methods[payment.method.name] += payment.amount
        cashiers[payment.created_by.display_name] += payment.amount
        collections += payment.amount
        monthly[payment.paid_on.strftime("%Y-%m")] += payment.amount
        if payment.paid_on == school_day():
            today_collected += payment.amount
    balance = trial_balance(through=today)
    interval = trial_balance(through=today, start=start)
    earned = sum(
        (row["credit"] - row["debit"] for row in interval if row["account__kind"] == "income"), ZERO
    )
    discounts = sum(
        (
            row["debit"] - row["credit"]
            for row in interval
            if row["account__kind"] == "contra_income"
        ),
        ZERO,
    )
    expenses = sum(
        (row["debit"] - row["credit"] for row in interval if row["account__kind"] == "expense"),
        ZERO,
    )
    refunds = Refund.objects.filter(request__occurred_on__lte=today)
    if start:
        refunds = refunds.filter(request__occurred_on__gte=start)
    expense_rows = Expense.objects.filter(
        request__state="approved", occurred_on__lte=today
    ).select_related("category", "request")
    if start:
        expense_rows = expense_rows.filter(occurred_on__gte=start)
    if expense_rows.count() > LIMIT:
        raise ValidationError("Narrow the expense report to at most 5,000 documents.")
    expense_register = list(expense_rows)
    expense_categories = defaultdict(lambda: ZERO)
    for expense in expense_register:
        expense_categories[expense.category.name] += expense.amount
    categories = defaultdict(lambda: ZERO)
    # Recognition is dated by the economic event, rather than by the collection date.
    earned_lines = (
        InvoiceLine.objects.filter(invoice__issue_on__lte=today, details__treatment="earned")
        .exclude(invoice__state__in=["draft", "approved"])
        .select_related("invoice", "category")
    )
    if start:
        earned_lines = earned_lines.filter(invoice__issue_on__gte=start)
    for line in earned_lines:
        categories[line.category.name] += line.gross
    adjustments = JournalLine.objects.filter(
        journal__state="posted", account__kind="income", journal__occurred_on__lte=today
    ).exclude(journal__source_type="invoice")
    if start:
        adjustments = adjustments.filter(journal__occurred_on__gte=start)
    # Credits/recognition/fines remain explicitly visible; no allocation-based revenue inference.
    for row in adjustments.select_related("journal"):
        categories[row.journal.source_type] += row.credit - row.debit
    billed_monthly = defaultdict(lambda: ZERO)
    for row in invoices:
        billed_monthly[row["invoice"].issue_on.strftime("%Y-%m")] += row["effective"]
    return {
        "payment_register": payment_register,
        "expense_register": expense_register,
        "daily": dict(daily),
        "methods": dict(methods),
        "cashiers": dict(cashiers),
        "revenue_categories": dict(categories),
        "expense_categories": dict(expense_categories),
        "month_collected": monthly.get(school_day().strftime("%Y-%m"), ZERO),
        "invoices": invoices,
        "invoiced": billed,
        "collected": collections,
        "today_collected": today_collected,
        "outstanding": sum((row["balance"] for row in invoices), ZERO),
        "aging": aging,
        "classes": dict(classes),
        "monthly": dict(sorted(monthly.items())),
        "revenue": earned,
        "discounts": discounts,
        "expenses": expenses,
        "net_income": earned - discounts - expenses,
        "trial_balance": balance,
        "advance": -net_balance(control="advance", through=today),
        "deposit": -net_balance(control="deposit", through=today),
        "refunds": refunds.aggregate(total=Sum("amount"))["total"] or ZERO,
        "cash_accounts": [
            {"account": r["account__name"], "balance": r["debit"] - r["credit"]}
            for r in balance
            if r["account__control"] in ("cash", "bank")
        ],
        "chart": {
            "collections": {k: str(v) for k, v in sorted(monthly.items())},
            "aging": {k: str(v) for k, v in aging.items()},
            "classes": {k: str(v) for k, v in classes.items()},
            "revenue": {k: str(v) for k, v in categories.items()},
            "expenses": {k: str(v) for k, v in expense_categories.items()},
            "billing": {k: str(v) for k, v in sorted(billed_monthly.items())},
        },
    }


def statement(student, *, start=None, end=None):
    rows = (
        JournalLine.objects.filter(
            student=student,
            journal__state="posted",
            account__control__in=["receivable", "advance", "deposit", "deposit_due"],
        )
        .select_related("journal", "account")
        .order_by("journal__occurred_on", "created_at", "pk")
    )
    if end:
        rows = rows.filter(journal__occurred_on__lte=end)
    opening = {key: ZERO for key in ("receivable", "advance", "deposit", "deposit_due")}
    if start:
        for row in rows.filter(journal__occurred_on__lt=start):
            opening[row.account.control] += row.debit - row.credit
        rows = rows.filter(journal__occurred_on__gte=start)
    if rows.count() > LIMIT:
        raise ValidationError("Narrow the statement to at most 5,000 postings.")
    balances = dict(opening)
    result = []
    for row in rows:
        balances[row.account.control] += row.debit - row.credit
        result.append(
            {
                "date": row.journal.occurred_on,
                "source": row.journal.source_type,
                "memo": row.journal.memo,
                "account": row.account.name,
                "debit": row.debit,
                "credit": row.credit,
                "owed": balances["receivable"],
                "advance": -balances["advance"],
                "deposit": -balances["deposit"],
            }
        )
    return {
        "rows": result,
        "opening": {
            "Amount owed": opening["receivable"],
            "Advance held": -opening["advance"],
            "Funded deposit": -opening["deposit"],
            "Uncollected deposit": -opening["deposit_due"],
        },
        "closing": balances,
    }
