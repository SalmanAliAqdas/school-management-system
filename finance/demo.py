"""Append-only fictional finance examples; never reconfigure an existing finance ledger."""

import uuid
from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import transaction

from people.models import GuardianStudent

from .approvals import decide_request, request_action
from .billing import generate_invoices, issue_invoice
from .common import control, initialize
from .models import (
    BillingCycle,
    ConcessionType,
    ExpenseCategory,
    FeeCategory,
    FeeLine,
    FeeStructure,
    FinanceSettings,
    FinancialPeriod,
    FinancialYear,
    PaymentMethod,
)
from .payments import collect_payment
from .reconciliation import pay_expense, request_expense
from .setup import save_setup


@transaction.atomic
def seed_finance_demo(accounts, year, students, sections):
    from django.conf import settings as django_settings

    if not django_settings.DEBUG or not django_settings.ALLOW_DEMO_DATA:
        raise ValidationError("Fictional finance seeding requires explicit local demo mode.")
    if FinanceSettings.objects.exists() or year.status != "open":
        return
    if (
        len(students) != 6
        or any(not p.admission_number.startswith("DEMO-") for p in students)
        or any(not u.email.endswith("@example.invalid") for u in accounts.values())
    ):
        raise ValidationError("Finance examples require the verified fictional demo school.")
    admin, clerk, principal = (
        accounts[k] for k in ("demo.admin", "demo.accountant", "demo.principal")
    )
    with patch(
        "finance.common.school_now",
        return_value=datetime(2026, 10, 23, 12, tzinfo=ZoneInfo("Asia/Karachi")),
    ):
        settings = initialize(admin)
        settings.backdate_days = 365
        settings.symbol = "Rs"
        save_setup(admin, settings)
        financial_year = save_setup(
            admin,
            FinancialYear(name="DEMO FY 2026-27", starts_on=year.starts_on, ends_on=year.ends_on),
        )
        for name, start, end in [
            ("August-September", date(2026, 8, 1), date(2026, 9, 30)),
            ("October", date(2026, 10, 1), date(2026, 10, 31)),
            ("November-July", date(2026, 11, 1), date(2027, 7, 31)),
        ]:
            save_setup(
                admin,
                FinancialPeriod(
                    financial_year=financial_year, name=name, starts_on=start, ends_on=end
                ),
            )
        tuition = save_setup(
            admin,
            FeeCategory(
                name="DEMO Tuition",
                starts_on=year.starts_on,
                income_account=control("revenue"),
                refundable=True,
            ),
        )
        deposit = save_setup(
            admin,
            FeeCategory(
                name="DEMO Security deposit",
                starts_on=year.starts_on,
                income_account=control("revenue"),
                treatment="deposit",
                recurring=False,
                refundable=True,
                late_fee_eligible=False,
            ),
        )
        annual = save_setup(
            admin,
            FeeCategory(
                name="DEMO Annual activities",
                starts_on=year.starts_on,
                income_account=control("revenue"),
                recurring=False,
            ),
        )
        for index, section in enumerate(sections):
            structure = save_setup(
                admin,
                FeeStructure(
                    name=f"DEMO {section.school_class} monthly",
                    academic_year=year,
                    school_class=section.school_class,
                    frequency="monthly",
                    starts_on=year.starts_on,
                    ends_on=year.ends_on,
                ),
            )
            save_setup(
                admin, FeeLine(structure=structure, category=tuition, amount=6000 + index * 500)
            )
            once = save_setup(
                admin,
                FeeStructure(
                    name=f"DEMO {section.school_class} one-time",
                    academic_year=year,
                    school_class=section.school_class,
                    frequency="once",
                    starts_on=year.starts_on,
                    ends_on=year.ends_on,
                ),
            )
            save_setup(admin, FeeLine(structure=once, category=deposit, amount=1000))
            save_setup(admin, FeeLine(structure=once, category=annual, amount=2500))
        guardian = students[0].guardian_links.first().guardian
        GuardianStudent.objects.get_or_create(
            guardian=guardian, student=students[1], defaults={"relationship": "Guardian"}
        )
        merit = save_setup(
            admin, ConcessionType(name="DEMO Merit scholarship", mode="percent", default_value=10)
        )
        sibling = save_setup(
            admin,
            ConcessionType(
                name="DEMO Sibling concession",
                mode="fixed",
                default_value=500,
                eligibility="siblings",
            ),
        )
        for student, concession in ((students[0], merit), (students[1], sibling)):
            r = request_action(
                admin,
                "discount",
                student=student,
                amount_value=concession.default_value,
                day=date(2026, 9, 1),
                reason="Verified fictional concession eligibility",
                payload={
                    "concession_type": str(concession.pk),
                    "category": str(tuition.pk),
                    "starts_on": year.starts_on.isoformat(),
                    "ends_on": year.ends_on.isoformat(),
                },
            )
            decide_request(
                principal, r.pk, approve=True, reason="Fictional eligibility independently approved"
            )
        cycle = save_setup(
            admin,
            BillingCycle(
                name="DEMO October fees",
                academic_year=year,
                frequency="monthly",
                starts_on=date(2026, 10, 1),
                ends_on=date(2026, 10, 31),
                issue_on=date(2026, 10, 1),
                due_on=date(2026, 10, 10),
            ),
        )
        outcome = generate_invoices(clerk, cycle.pk, students)
        if outcome["failed"]:
            raise ValidationError(str(outcome["failed"]))
        invoices = {}
        for invoice in outcome["generated"]:
            r = request_action(
                clerk,
                "issue_invoice",
                invoice=invoice,
                day=invoice.issue_on,
                reason="Review fictional monthly invoice before issue",
            )
            decide_request(
                principal, r.pk, approve=True, reason="Fictional monthly invoice approved"
            )
            invoices[invoice.student_id] = issue_invoice(clerk, invoice.pk)
        cash = save_setup(admin, PaymentMethod(name="DEMO Cash, manual", account=control("cash")))
        bank = save_setup(
            admin, PaymentMethod(name="DEMO Bank transfer, manual", account=control("bank"))
        )
        for index, student in enumerate(students[:4]):
            invoice = invoices[student.pk]
            value = (
                invoice.total
                if index == 0
                else 4000
                if index == 1
                else invoice.total + 2000
                if index == 2
                else 3000
            )
            allocate = min(value, invoice.total)
            payment = collect_payment(
                clerk,
                student=student,
                value=value,
                day=date(2026, 10, 20),
                method=cash if index % 2 == 0 else bank,
                reference=f"DEMO-COLLECTION-{index + 1}",
                idempotency_key=uuid.uuid5(uuid.NAMESPACE_URL, f"schoolos-demo-payment-{index}"),
                allocations=[{"invoice": invoice.pk, "amount": allocate}],
            )
            if index == 2:
                r = request_action(
                    clerk,
                    "refund_credit",
                    credit=payment.credit_lot,
                    amount_value=500,
                    day=date(2026, 10, 21),
                    target_account=control("cash"),
                    reason="Fictional excess advance credit return",
                )
                decide_request(
                    principal,
                    r.pk,
                    approve=True,
                    reason="Fictional credit return independently approved",
                )
        category = save_setup(
            admin, ExpenseCategory(name="DEMO Classroom supplies", account=control("expense"))
        )
        expense = request_expense(
            clerk,
            category=category,
            day=date(2026, 10, 20),
            payee="Fictional Learning Supplies",
            value=2500,
            description="Fictional classroom stationery purchase",
        )
        decide_request(
            principal, expense.request_id, approve=True, reason="Fictional supply purchase approved"
        )
        pay_expense(clerk, expense.pk, control("cash"), date(2026, 10, 21), "DEMO-EXPENSE-001")
        r = request_action(
            clerk,
            "transfer",
            amount_value=1000,
            day=date(2026, 10, 21),
            source_account=control("cash"),
            target_account=control("bank"),
            reason="Fictional cash deposited in manual bank book",
        )
        decide_request(
            principal, r.pk, approve=True, reason="Fictional cash movement independently approved"
        )
