import uuid
from datetime import date
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, transaction
from django.test import TestCase

from finance.approvals import decide_request, request_action
from finance.billing import generate_invoices, issue_invoice
from finance.common import amount, control, initialize
from finance.ledger import assert_consistent, student_balances
from finance.models import (
    BillingCycle,
    FeeCategory,
    FeeLine,
    FeeStructure,
    FinancialPeriod,
    FinancialYear,
    Invoice,
    JournalEntry,
    JournalLine,
    Payment,
    PaymentMethod,
)
from finance.payments import allocate_credit, collect_payment, invoice_totals, lot_available
from finance.setup import save_setup

from .helpers import make_school_data, make_user

DAY = date(2026, 10, 23)


class FinanceFixture:
    def setUp(self):
        from datetime import datetime
        from unittest.mock import patch
        from zoneinfo import ZoneInfo

        clock = patch(
            "finance.common.school_now",
            return_value=datetime(2026, 10, 23, 12, tzinfo=ZoneInfo("Asia/Karachi")),
        )
        clock.start()
        self.addCleanup(clock.stop)

    @classmethod
    def setUpTestData(cls):
        cls.data = make_school_data()
        cls.admin = make_user("financeadmin", "System Administrator")
        cls.principal = make_user("financeprincipal", "Principal")
        cls.accountant = cls.data["accountant"]
        cls.student = cls.data["own"]
        cls.settings = initialize(cls.admin)
        cls.settings.invoice_approval = False
        cls.settings.backdate_days = 365
        cls.settings.save()
        cls.year = save_setup(
            cls.admin,
            FinancialYear(name="FY2026", starts_on=date(2026, 1, 1), ends_on=date(2026, 12, 31)),
        )
        cls.period = save_setup(
            cls.admin,
            FinancialPeriod(
                financial_year=cls.year,
                name="2026",
                starts_on=cls.year.starts_on,
                ends_on=cls.year.ends_on,
            ),
        )
        cls.category = save_setup(
            cls.admin,
            FeeCategory(
                name="Tuition",
                income_account=control("revenue"),
                starts_on=date(2026, 1, 1),
                refundable=True,
            ),
        )
        cls.structure = save_setup(
            cls.admin,
            FeeStructure(
                name="Grade 6",
                academic_year=cls.data["year"],
                school_class=cls.data["section"].school_class,
                frequency="monthly",
                starts_on=date(2026, 8, 1),
                ends_on=date(2027, 7, 31),
            ),
        )
        cls.fee = save_setup(
            cls.admin, FeeLine(structure=cls.structure, category=cls.category, amount=10000)
        )
        cls.cycle = save_setup(
            cls.admin,
            BillingCycle(
                academic_year=cls.data["year"],
                name="October",
                frequency="monthly",
                starts_on=date(2026, 10, 1),
                ends_on=date(2026, 10, 31),
                issue_on=date(2026, 10, 1),
                due_on=date(2026, 10, 10),
            ),
        )
        cls.method = save_setup(
            cls.admin, PaymentMethod(name="Manual cash", account=control("cash"))
        )

    def invoice(self):
        result = generate_invoices(self.accountant, self.cycle.pk, [self.student])
        self.assertEqual(result["failed"], [])
        return issue_invoice(self.accountant, result["generated"][0].pk)

    def payment(self, value, invoice=None, allocation=None, **kwargs):
        return collect_payment(
            self.accountant,
            student=self.student,
            value=value,
            day=DAY,
            method=self.method,
            reference=str(uuid.uuid4()),
            idempotency_key=uuid.uuid4(),
            allocations=[{"invoice": invoice.pk, "amount": allocation or value}] if invoice else [],
            **kwargs,
        )

    def approve(self, kind, **kwargs):
        request = request_action(
            self.accountant, kind, day=DAY, reason="Verified fictional finance action", **kwargs
        )
        return decide_request(
            self.principal,
            request.pk,
            approve=True,
            reason="Independently verified fictional action",
        )


class FinanceCoreTests(FinanceFixture, TestCase):
    def test_invoice_arithmetic(self):
        invoice = self.invoice()
        self.assertEqual(invoice.total, Decimal("10000"))
        self.assertEqual(student_balances(self.student)["owed"], invoice.total)
        self.assertTrue(assert_consistent()["balanced"])

    def test_duplicate_generation(self):
        self.invoice()
        result = generate_invoices(self.accountant, self.cycle.pk, [self.student])
        self.assertEqual(len(result["skipped"]), 1)
        self.assertEqual(Invoice.objects.count(), 1)

    def test_partial_collections(self):
        invoice = self.invoice()
        self.payment("4000", invoice)
        self.payment("3000", invoice)
        self.assertEqual(invoice_totals(invoice)["balance"], Decimal("3000"))
        self.assertEqual(student_balances(self.student)["advance"], 0)
        self.assertTrue(assert_consistent()["balanced"])

    def test_excess_becomes_advance(self):
        invoice = self.invoice()
        payment = self.payment("12000", invoice, allocation="10000")
        self.assertEqual(lot_available(payment.credit_lot), 2000)
        self.assertEqual(student_balances(self.student)["advance"], 2000)
        self.assertEqual(invoice_totals(invoice)["status"], "paid")

    def test_overallocation_rolls_back(self):
        invoice = self.invoice()
        with self.assertRaises(ValidationError):
            self.payment("12000", invoice)
        self.assertFalse(Payment.objects.exists())
        self.assertEqual(student_balances(self.student)["owed"], 10000)

    def test_payment_idempotency(self):
        token = uuid.uuid4()
        arguments = dict(
            student=self.student,
            value="500",
            day=DAY,
            method=self.method,
            reference="same-reference",
            idempotency_key=token,
        )
        one = collect_payment(self.accountant, **arguments)
        two = collect_payment(self.accountant, **arguments)
        self.assertEqual(one.pk, two.pk)
        self.assertEqual(Payment.objects.count(), 1)
        arguments["value"] = "600"
        with self.assertRaises(ValidationError):
            collect_payment(self.accountant, **arguments)

    def test_duplicate_reference(self):
        args = dict(
            student=self.student,
            value="500",
            day=DAY,
            method=self.method,
            reference="duplicate",
            idempotency_key=uuid.uuid4(),
        )
        collect_payment(self.accountant, **args)
        args["idempotency_key"] = uuid.uuid4()
        with self.assertRaises(ValidationError):
            collect_payment(self.accountant, **args)

    def test_money_precision(self):
        for value in ("NaN", "Infinity", "-1", "1.001", "1e100", 1.2, True):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                amount(value, self.settings)

    def test_teacher_cannot_collect(self):
        with self.assertRaises(PermissionDenied):
            collect_payment(
                self.data["teacher_user"],
                student=self.student,
                value=10,
                day=DAY,
                method=self.method,
                reference="blocked",
                idempotency_key=uuid.uuid4(),
            )

    def test_accountant_cannot_approve(self):
        invoice = self.invoice()
        request = request_action(
            self.accountant,
            "credit",
            invoice=invoice,
            line=invoice.lines.first(),
            amount_value="500",
            day=DAY,
            reason="Fictional credit request",
        )
        with self.assertRaises(PermissionDenied):
            decide_request(
                self.accountant, request.pk, approve=True, reason="Self decision blocked"
            )

    def test_independent_approval(self):
        invoice = self.invoice()
        request = request_action(
            self.principal,
            "credit",
            invoice=invoice,
            line=invoice.lines.first(),
            amount_value="500",
            day=DAY,
            reason="Fictional credit request",
        )
        with self.assertRaises(ValidationError):
            decide_request(self.principal, request.pk, approve=True, reason="Self decision blocked")

    def test_credit_releases_excess_allocation(self):
        invoice = self.invoice()
        self.payment("10000", invoice)
        self.approve("credit", invoice=invoice, line=invoice.lines.first(), amount_value="2000")
        self.assertEqual(invoice_totals(invoice)["balance"], 0)
        self.assertEqual(student_balances(self.student)["advance"], 2000)
        self.assertEqual(student_balances(self.student)["owed"], 0)

    def test_advance_refund(self):
        payment = self.payment("3000")
        self.approve(
            "refund_credit",
            credit=payment.credit_lot,
            amount_value="2000",
            target_account=control("cash"),
        )
        self.assertEqual(student_balances(self.student)["advance"], 1000)
        self.assertEqual(lot_available(payment.credit_lot), 1000)

    def test_pending_refund_reserves_credit(self):
        payment = self.payment("3000")
        request_action(
            self.accountant,
            "refund_credit",
            credit=payment.credit_lot,
            amount_value="2000",
            target_account=control("cash"),
            day=DAY,
            reason="Reserve fictional credit refund",
        )
        with self.assertRaises(ValidationError):
            request_action(
                self.accountant,
                "refund_credit",
                credit=payment.credit_lot,
                amount_value="2000",
                target_account=control("cash"),
                day=DAY,
                reason="Second refund should fail",
            )
        self.assertEqual(lot_available(payment.credit_lot), 1000)

    def test_refund_fee_with_partial_payment(self):
        invoice = self.invoice()
        self.payment("4000", invoice)
        self.approve(
            "refund_fee",
            invoice=invoice,
            line=invoice.lines.first(),
            amount_value="1000",
            target_account=control("cash"),
        )
        self.assertEqual(invoice_totals(invoice)["balance"], 6000)
        self.assertEqual(student_balances(self.student)["advance"], 0)
        self.assertEqual(student_balances(self.student)["owed"], 6000)

    def test_payment_reversal(self):
        invoice = self.invoice()
        payment = self.payment("4000", invoice)
        original = payment.snapshot
        self.approve("reverse_payment", payment=payment)
        payment.refresh_from_db()
        self.assertEqual(payment.snapshot, original)
        self.assertEqual(invoice_totals(invoice)["balance"], 10000)
        self.assertEqual(student_balances(self.student)["advance"], 0)

    def test_refunded_payment_cannot_reverse(self):
        payment = self.payment("3000")
        self.approve(
            "refund_credit",
            credit=payment.credit_lot,
            amount_value="1000",
            target_account=control("cash"),
        )
        with self.assertRaises(ValidationError):
            self.approve("reverse_payment", payment=payment)

    def test_void_unpaid(self):
        invoice = self.invoice()
        self.approve("void", invoice=invoice)
        invoice.refresh_from_db()
        self.assertEqual(invoice.state, "voided")
        self.assertEqual(student_balances(self.student)["owed"], 0)

    def test_void_paid_rejected(self):
        invoice = self.invoice()
        self.payment("100", invoice)
        with self.assertRaises(ValidationError):
            self.approve("void", invoice=invoice)

    def test_used_fee_definition_protected(self):
        self.invoice()
        self.fee.amount = 11000
        with self.assertRaises(ValidationError):
            save_setup(self.admin, self.fee)

    def test_currency_frozen(self):
        self.settings.currency = "USD"
        with self.assertRaises(ValidationError):
            save_setup(self.admin, self.settings)

    def test_posted_journal_immutable(self):
        self.invoice()
        with self.assertRaises(DatabaseError), transaction.atomic():
            JournalEntry.objects.update(memo="edited")

    def test_posted_lines_immutable(self):
        self.invoice()
        with self.assertRaises(DatabaseError), transaction.atomic():
            JournalLine.objects.update(debit=1)

    def test_receipt_immutable(self):
        payment = self.payment("2000")
        with self.assertRaises(DatabaseError), transaction.atomic():
            Payment.objects.filter(pk=payment.pk).update(amount=1)

    def test_invoice_lines_immutable(self):
        invoice = self.invoice()
        with self.assertRaises(DatabaseError), transaction.atomic():
            invoice.lines.update(description="edited")

    def test_one_decision(self):
        invoice = self.invoice()
        request = self.approve(
            "credit", invoice=invoice, line=invoice.lines.first(), amount_value="100"
        )
        with self.assertRaises(ValidationError):
            decide_request(self.admin, request.pk, approve=True, reason="Cannot decide twice")

    def test_non_enrolled_student_skipped(self):
        result = generate_invoices(self.accountant, self.cycle.pk, [self.data["unassigned"]])
        self.assertEqual(len(result["skipped"]), 1)

    def test_allocate_existing_advance(self):
        invoice = self.invoice()
        payment = self.payment("3000")
        allocate_credit(
            self.accountant,
            payment.credit_lot.pk,
            invoice.pk,
            "2000",
            DAY,
            idempotency_key=uuid.uuid4(),
        )
        self.assertEqual(invoice_totals(invoice)["balance"], 8000)
        self.assertEqual(student_balances(self.student)["advance"], 1000)


class FinanceAdvancedTests(FinanceFixture, TestCase):
    def test_deposit_is_liability_and_only_funded_amount_refundable(self):
        category = save_setup(
            self.admin,
            FeeCategory(
                name="Deposit",
                income_account=control("revenue"),
                starts_on=date(2026, 8, 1),
                treatment="deposit",
                refundable=True,
                late_fee_eligible=False,
            ),
        )
        save_setup(self.admin, FeeLine(structure=self.structure, category=category, amount=1000))
        invoice = self.invoice()
        payment = self.payment("10500", invoice)
        balances = student_balances(self.student)
        self.assertEqual(balances["deposit"], 500)
        self.assertEqual(balances["deposit_due"], 500)
        allocation = payment.credit_lot.allocations.get(line__category=category)
        self.approve(
            "refund_deposit",
            allocation=allocation,
            amount_value="300",
            target_account=control("cash"),
        )
        self.assertEqual(student_balances(self.student)["deposit"], 200)
        self.assertEqual(invoice_totals(invoice)["balance"], 500)
        with self.assertRaises(ValidationError):
            self.approve(
                "refund_deposit",
                allocation=allocation,
                amount_value="300",
                target_account=control("cash"),
            )

    def test_deferred_revenue_recognition_and_credit(self):
        from finance.ledger import net_balance

        self.category.treatment = "deferred"
        save_setup(self.admin, self.category)
        invoice = self.invoice()
        line = invoice.lines.first()
        self.assertEqual(net_balance(control="deferred"), -10000)
        self.assertEqual(net_balance(control="revenue"), 0)
        self.approve("recognize", invoice=invoice, line=line, amount_value="6000")
        self.assertEqual(net_balance(control="deferred"), -4000)
        self.approve("credit", invoice=invoice, line=line, amount_value="5000")
        self.assertEqual(net_balance(control="deferred"), 0)
        self.assertEqual(net_balance(control="revenue"), -5000)
        self.assertEqual(student_balances(self.student)["owed"], 5000)

    def test_fixed_discount(self):
        from finance.models import ConcessionType

        concession = save_setup(
            self.admin, ConcessionType(name="Merit", mode="fixed", default_value=1500)
        )
        r = request_action(
            self.admin,
            "discount",
            student=self.student,
            amount_value=1500,
            day=DAY,
            reason="Verified merit eligibility",
            payload={
                "concession_type": str(concession.pk),
                "starts_on": "2026-08-01",
                "ends_on": "2027-07-31",
            },
        )
        decide_request(
            self.principal, r.pk, approve=True, reason="Independently verified merit award"
        )
        self.assertEqual(self.invoice().total, 8500)

    def test_discount_stacking_blocked(self):
        from finance.models import ConcessionType

        for name in ("Merit", "Custom"):
            concession = save_setup(
                self.admin, ConcessionType(name=name, mode="percent", default_value=10)
            )
            r = request_action(
                self.admin,
                "discount",
                student=self.student,
                amount_value=10,
                day=DAY,
                reason="Verified fictional concession",
                payload={
                    "concession_type": str(concession.pk),
                    "starts_on": "2026-08-01",
                    "ends_on": "2027-07-31",
                },
            )
            decide_request(
                self.principal, r.pk, approve=True, reason="Independently approved award"
            )
        result = generate_invoices(self.accountant, self.cycle.pk, [self.student])
        self.assertEqual(len(result["failed"]), 1)
        self.assertFalse(Invoice.objects.exists())

    def test_prorated_withdrawal_preserves_prior_invoice(self):
        from people.models import Enrollment

        placement = Enrollment.objects.get(student=self.student, academic_year=self.data["year"])
        invoice = self.invoice()
        original = invoice.snapshot
        placement.ended_on = date(2026, 10, 15)
        placement.is_active = False
        placement.save()
        invoice.refresh_from_db()
        self.assertEqual(invoice.snapshot, original)
        self.assertEqual(invoice.total, 10000)
        # A separately selected future billing period skips this withdrawn student.
        cycle = save_setup(
            self.admin,
            BillingCycle(
                academic_year=self.data["year"],
                name="November",
                frequency="monthly",
                starts_on=date(2026, 11, 1),
                ends_on=date(2026, 11, 30),
                issue_on=date(2026, 11, 1),
                due_on=date(2026, 11, 10),
            ),
        )
        self.assertEqual(
            len(generate_invoices(self.accountant, cycle.pk, [self.student])["skipped"]), 1
        )

    def test_proration_before_billing(self):
        from people.models import Enrollment

        placement = Enrollment.objects.get(student=self.student, academic_year=self.data["year"])
        placement.ended_on = date(2026, 10, 15)
        placement.is_active = False
        placement.save()
        self.assertEqual(self.invoice().total, Decimal("4838.71"))

    def test_future_revision_preserves_invoice(self):
        invoice = self.invoice()
        revised = save_setup(
            self.admin,
            FeeStructure(
                name="November revision",
                academic_year=self.data["year"],
                school_class=self.structure.school_class,
                frequency="monthly",
                starts_on=date(2026, 11, 1),
                ends_on=date(2027, 7, 31),
                revises=self.structure,
            ),
        )
        save_setup(self.admin, FeeLine(structure=revised, category=self.category, amount=12000))
        invoice.refresh_from_db()
        self.assertEqual(invoice.total, 10000)
        self.assertEqual(revised.family, self.structure.family)
        self.assertEqual(revised.revision, 2)

    def test_late_fee_idempotency_and_waiver(self):
        from finance.fines import apply_late_fee

        invoice = self.invoice()
        self.settings.fine_mode = "fixed"
        self.settings.fine_value = 100
        save_setup(self.admin, self.settings)
        one = apply_late_fee(self.accountant, invoice.pk, day=DAY)
        two = apply_late_fee(self.accountant, invoice.pk, day=DAY)
        self.assertEqual(one.pk, two.pk)
        self.assertEqual(invoice_totals(invoice)["balance"], 10100)
        self.approve("fine_waiver", invoice=invoice, charge=one, amount_value=100)
        self.assertEqual(invoice_totals(invoice)["balance"], 10000)

    def test_expense_approval_and_payment(self):
        from finance.ledger import net_balance
        from finance.models import ExpenseCategory
        from finance.reconciliation import pay_expense, request_expense

        category = save_setup(
            self.admin, ExpenseCategory(name="Supplies", account=control("expense"))
        )
        expense = request_expense(
            self.accountant,
            category=category,
            day=DAY,
            payee="Fictional Shop",
            value="2500",
            description="Fictional school supplies",
        )
        with self.assertRaises(ValidationError):
            pay_expense(self.accountant, expense.pk, control("cash"), DAY, "expense-1")
        decide_request(
            self.principal,
            expense.request_id,
            approve=True,
            reason="Independently verified expense",
        )
        pay_expense(self.accountant, expense.pk, control("cash"), DAY, "expense-1")
        self.assertEqual(net_balance(control="expense"), 2500)
        self.assertEqual(net_balance(control="payable"), 0)
        with self.assertRaises(ValidationError):
            pay_expense(self.accountant, expense.pk, control("cash"), DAY, "expense-2")

    def test_transfer_has_no_income(self):
        from finance.ledger import net_balance

        self.approve(
            "transfer",
            source_account=control("cash"),
            target_account=control("bank"),
            amount_value=1000,
        )
        self.assertEqual(net_balance(control="cash"), -1000)
        self.assertEqual(net_balance(control="bank"), 1000)
        self.assertEqual(net_balance(control="revenue"), 0)

    def test_manual_reconciliation(self):
        from finance.models import ReconciliationLine
        from finance.reconciliation import request_reconciliation

        self.payment("3000")
        row = JournalLine.objects.get(account=control("cash"))
        payload = {
            "starts_on": DAY.isoformat(),
            "ends_on": DAY.isoformat(),
            "opening": "0",
            "closing": "3000",
            "lines": [row.pk],
        }
        r = request_reconciliation(
            self.accountant, control("cash"), payload, "Fictional manual bank statement review"
        )
        with self.assertRaises(ValidationError):
            request_reconciliation(
                self.accountant, control("cash"), payload, "Duplicate clearing must be blocked"
            )
        decide_request(self.principal, r.pk, approve=True, reason="Independently matched statement")
        self.assertTrue(ReconciliationLine.objects.get(line=row).is_active)

    def test_reconciliation_mismatch_blocked(self):
        from finance.reconciliation import request_reconciliation

        with self.assertRaises(ValidationError):
            request_reconciliation(
                self.accountant,
                control("cash"),
                {
                    "starts_on": DAY.isoformat(),
                    "ends_on": DAY.isoformat(),
                    "opening": "0",
                    "closing": "10",
                    "lines": [],
                },
                "Statement does not match book",
            )

    def test_report_calculations(self):
        from finance.reporting import financial_report

        invoice = self.invoice()
        self.payment("4000", invoice)
        data = financial_report(self.accountant)
        self.assertEqual(data["invoiced"], 10000)
        self.assertEqual(data["collected"], 4000)
        self.assertEqual(data["outstanding"], 6000)
        self.assertEqual(data["revenue"], 10000)

    def test_required_invoice_approval(self):
        self.settings.invoice_approval = True
        save_setup(self.admin, self.settings)
        result = generate_invoices(self.accountant, self.cycle.pk, [self.student])
        invoice = result["generated"][0]
        with self.assertRaises(ValidationError):
            issue_invoice(self.accountant, invoice.pk)
        r = request_action(
            self.accountant,
            "issue_invoice",
            invoice=invoice,
            day=invoice.issue_on,
            reason="Approve fictional invoice",
        )
        decide_request(self.principal, r.pk, approve=True, reason="Invoice independently verified")
        self.assertEqual(issue_invoice(self.accountant, invoice.pk).state, "issued")

    def test_high_payment_pending_until_independent_approval(self):
        self.settings.payment_approval_threshold = 1000
        save_setup(self.admin, self.settings)
        payment = self.payment("2000")
        self.assertEqual(payment.state, "pending")
        self.assertEqual(student_balances(self.student)["advance"], 0)
        from finance.models import FinancialRequest

        r = FinancialRequest.objects.get(payment=payment)
        decide_request(self.principal, r.pk, approve=True, reason="Payment independently verified")
        payment.refresh_from_db()
        self.assertEqual(payment.state, "posted")
        self.assertEqual(student_balances(self.student)["advance"], 2000)

    def test_db_used_structure_protection(self):
        self.invoice()
        with self.assertRaises(DatabaseError), transaction.atomic():
            FeeStructure.objects.filter(pk=self.structure.pk).update(starts_on=date(2026, 9, 1))

    def test_multiple_invoice_allocations(self):
        invoice = self.invoice()
        cycle = save_setup(
            self.admin,
            BillingCycle(
                academic_year=self.data["year"],
                name="September",
                frequency="monthly",
                starts_on=date(2026, 9, 1),
                ends_on=date(2026, 9, 30),
                issue_on=date(2026, 9, 1),
                due_on=date(2026, 9, 10),
            ),
        )
        second = generate_invoices(self.accountant, cycle.pk, [self.student])["generated"][0]
        second = issue_invoice(self.accountant, second.pk)
        collect_payment(
            self.accountant,
            student=self.student,
            value="7000",
            day=DAY,
            method=self.method,
            reference="two-invoices",
            idempotency_key=uuid.uuid4(),
            allocations=[
                {"invoice": invoice.pk, "amount": "4000"},
                {"invoice": second.pk, "amount": "3000"},
            ],
        )
        self.assertEqual(student_balances(self.student)["owed"], 13000)
        self.assertEqual(invoice_totals(invoice)["balance"], 6000)
        self.assertEqual(invoice_totals(second)["balance"], 7000)


class FinanceSecurityTests(FinanceFixture, TestCase):
    def login(self, user):
        from .helpers import BACKEND

        self.client.force_login(user, backend=BACKEND)

    def test_guardian_invoice_and_receipt_download(self):
        invoice = self.invoice()
        payment = self.payment("1000", invoice)
        self.login(self.data["parent"])
        for url in (
            f"/finance/invoices/{invoice.pk}/",
            f"/finance/receipts/{payment.pk}/",
            f"/finance/students/{self.student.pk}/",
        ):
            self.assertEqual(self.client.get(url).status_code, 200)
            response = self.client.get(url + "?format=pdf")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.content.startswith(b"%PDF-"))
            self.assertEqual(
                set(response["Cache-Control"].replace(" ", "").split(",")), {"private", "no-store"}
            )

    def test_guardian_unrelated_student_denied(self):
        self.login(self.data["parent"])
        self.assertEqual(
            self.client.get(f"/finance/students/{self.data['other'].pk}/").status_code, 404
        )

    def test_student_unrelated_invoice_denied(self):
        invoice = self.invoice()
        other = generate_invoices(self.accountant, self.cycle.pk, [self.data["other"]])[
            "generated"
        ][0]
        issue_invoice(self.accountant, other.pk)
        self.login(self.data["student_user"])
        self.assertEqual(self.client.get(f"/finance/invoices/{invoice.pk}/").status_code, 200)
        self.assertEqual(
            self.client.get(f"/finance/invoices/{other.pk}/?format=pdf").status_code, 404
        )

    def test_guardian_link_revocation(self):
        invoice = self.invoice()
        self.login(self.data["parent"])
        self.assertEqual(self.client.get(f"/finance/invoices/{invoice.pk}/").status_code, 200)
        from people.models import GuardianStudent

        GuardianStudent.objects.filter(
            guardian=self.data["guardian"], student=self.student
        ).delete()
        self.assertEqual(self.client.get(f"/finance/invoices/{invoice.pk}/").status_code, 404)
        self.assertNotContains(self.client.get("/finance/notices/"), invoice.number)

    def test_portal_policy_revocation(self):
        invoice = self.invoice()
        self.settings.guardian_portal = False
        save_setup(self.admin, self.settings)
        self.login(self.data["parent"])
        self.assertEqual(self.client.get(f"/finance/invoices/{invoice.pk}/").status_code, 404)

    def test_guardian_internal_finance_denied(self):
        self.login(self.data["parent"])
        for url in (
            "/finance/reports/?format=csv",
            "/finance/journal/",
            "/finance/collect/",
            "/finance/billing/",
            "/finance/requests/",
            "/finance/reconciliation/",
            "/finance/expenses/",
            "/finance/setup/accounts/",
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_teacher_finance_denied(self):
        self.login(self.data["teacher_user"])
        self.assertEqual(self.client.get("/finance/").status_code, 403)

    def test_accountant_setup_denied(self):
        self.login(self.accountant)
        for kind in ("settings", "accounts", "structures", "categories"):
            self.assertEqual(self.client.get(f"/finance/setup/{kind}/").status_code, 403)

    def test_accountant_screens(self):
        invoice = self.invoice()
        payment = self.payment("100", invoice)
        self.login(self.accountant)
        for url in (
            "/finance/",
            "/finance/invoices/",
            "/finance/billing/",
            "/finance/collect/",
            "/finance/receipts/",
            "/finance/students/",
            "/finance/allocate/",
            "/finance/requests/",
            "/finance/requests/new/",
            "/finance/expenses/",
            "/finance/expenses/new/",
            "/finance/reconciliation/",
            "/finance/reports/",
            "/finance/journal/",
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get(f"/finance/receipts/{payment.pk}/").status_code, 200)

    def test_setup_screens(self):
        self.login(self.admin)
        for kind in (
            "settings",
            "accounts",
            "years",
            "periods",
            "methods",
            "categories",
            "structures",
            "lines",
            "assignments",
            "concessions",
            "cycles",
            "expense-categories",
        ):
            with self.subTest(kind=kind):
                self.assertEqual(
                    self.client.get(f"/finance/setup/{kind}/", follow=True).status_code, 200
                )

    def test_notifications_and_reminders_idempotent(self):
        from finance.models import FinanceNotice
        from finance.notifications import send_reminders

        self.invoice()
        send_reminders(self.accountant)
        count = FinanceNotice.objects.count()
        send_reminders(self.accountant)
        self.assertEqual(FinanceNotice.objects.count(), count)
        self.assertGreater(count, 0)

    def test_reports_export_authorized(self):
        self.invoice()
        self.login(self.accountant)
        self.assertEqual(
            self.client.get("/finance/reports/?format=csv")["Content-Type"], "text/csv"
        )
        self.assertTrue(
            self.client.get("/finance/reports/?format=pdf").content.startswith(b"%PDF-")
        )


class FinancePolicyTests(FinanceFixture, TestCase):
    def test_dated_late_fee_exemption(self):
        from finance.fines import apply_late_fee

        invoice = self.invoice()
        self.settings.fine_mode = "fixed"
        self.settings.fine_value = 100
        save_setup(self.admin, self.settings)
        r = request_action(
            self.admin,
            "exempt_fines",
            student=self.student,
            day=DAY,
            reason="Fictional authorized fee exemption",
            payload={"starts_on": "2026-10-01", "ends_on": "2026-10-31"},
        )
        decide_request(
            self.principal, r.pk, approve=True, reason="Independently verified exemption"
        )
        with self.assertRaises(ValidationError):
            apply_late_fee(self.accountant, invoice.pk, day=DAY)

    def test_period_close_reopen_and_posting_block(self):
        from datetime import datetime
        from unittest.mock import patch
        from zoneinfo import ZoneInfo

        self.invoice()
        with patch(
            "finance.common.school_now",
            return_value=datetime(2027, 1, 1, 12, tzinfo=ZoneInfo("Asia/Karachi")),
        ):
            r = request_action(
                self.accountant,
                "close_period",
                period=self.period,
                day=date(2026, 12, 31),
                reason="Fictional month end closing review",
            )
            decide_request(
                self.principal, r.pk, approve=True, reason="Independently verified period closing"
            )
            self.period.refresh_from_db()
            self.assertTrue(self.period.is_closed)
            with self.assertRaises(ValidationError):
                self.payment("100")
            r = request_action(
                self.admin,
                "reopen_period",
                period=self.period,
                reason="Approved fictional exceptional reopening",
            )
            decide_request(
                self.principal,
                r.pk,
                approve=True,
                reason="Independently verified exceptional reopening",
            )
        self.period.refresh_from_db()
        self.assertFalse(self.period.is_closed)

    def test_closing_requires_cash_reconciliation(self):
        from datetime import datetime
        from unittest.mock import patch
        from zoneinfo import ZoneInfo

        self.payment("100")
        with patch(
            "finance.common.school_now",
            return_value=datetime(2027, 1, 1, 12, tzinfo=ZoneInfo("Asia/Karachi")),
        ):
            r = request_action(
                self.accountant,
                "close_period",
                period=self.period,
                day=date(2026, 12, 31),
                reason="Fictional closing with uncleared cash",
            )
            with self.assertRaises(ValidationError):
                decide_request(
                    self.principal, r.pk, approve=True, reason="Must fail for uncleared cash"
                )
        r.refresh_from_db()
        self.assertEqual(r.state, "pending")

    def test_historical_as_of_void(self):
        from finance.reporting import financial_report

        invoice = self.invoice()
        self.approve("void", invoice=invoice)
        data = financial_report(self.accountant, end=date(2026, 10, 15))
        self.assertEqual(data["invoiced"], 10000)
        self.assertEqual(data["outstanding"], 10000)
        self.assertEqual(financial_report(self.accountant)["invoiced"], 0)

    def test_bulk_confirmation_requires_matching_preview(self):
        from .helpers import BACKEND

        self.client.force_login(self.accountant, backend=BACKEND)
        data = {"cycle": str(self.cycle.pk), "students": [str(self.student.pk)], "confirm": "on"}
        self.assertContains(
            self.client.post("/finance/billing/", data), "Preview the exact batch first"
        )
        self.assertFalse(Invoice.objects.exists())
        data.pop("confirm")
        response = self.client.post("/finance/billing/", data)
        token = response.context["form"].data["preview_token"]
        data.update(confirm="on", preview_token=token)
        self.assertEqual(self.client.post("/finance/billing/", data).status_code, 302)
        self.assertEqual(Invoice.objects.count(), 1)

    def test_csrf_financial_mutation(self):
        from django.test import Client

        from .helpers import BACKEND

        client = Client(enforce_csrf_checks=True)
        client.force_login(self.accountant, backend=BACKEND)
        self.assertEqual(client.post("/finance/collect/", {}).status_code, 403)

    def test_invalid_attachment_rejected_privately(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from finance.models import ExpenseCategory
        from finance.reconciliation import request_expense

        category = save_setup(
            self.admin, ExpenseCategory(name="Supplies", account=control("expense"))
        )
        with self.assertRaises(ValidationError):
            request_expense(
                self.accountant,
                category=category,
                day=DAY,
                payee="Fictional",
                value=100,
                description="Fictional invalid receipt document",
                attachment=SimpleUploadedFile(
                    "receipt.png", b"<script>unsafe</script>", content_type="image/png"
                ),
            )

    def test_private_attachment_staff_only(self):
        from io import BytesIO
        from tempfile import TemporaryDirectory

        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings
        from PIL import Image

        from finance.models import ExpenseCategory
        from finance.reconciliation import request_expense

        from .helpers import BACKEND

        category = save_setup(
            self.admin, ExpenseCategory(name="Supplies", account=control("expense"))
        )
        buffer = BytesIO()
        Image.new("RGB", (10, 10), "white").save(buffer, format="PNG")
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            expense = request_expense(
                self.accountant,
                category=category,
                day=DAY,
                payee="Fictional",
                value=100,
                description="Fictional sanitized receipt scan",
                attachment=SimpleUploadedFile(
                    "receipt.png", buffer.getvalue(), content_type="image/png"
                ),
            )
            self.client.force_login(self.accountant, backend=BACKEND)
            self.assertEqual(
                self.client.get(f"/finance/expenses/{expense.pk}/attachment/").status_code, 200
            )
            self.client.force_login(self.data["parent"], backend=BACKEND)
            self.assertEqual(
                self.client.get(f"/finance/expenses/{expense.pk}/attachment/").status_code, 403
            )

    def test_percent_discount_order_and_expiry(self):
        from finance.models import ConcessionType

        self.settings.allow_discount_stacking = True
        save_setup(self.admin, self.settings)
        for name, mode, value in [("Fixed", "fixed", 1000), ("Percent", "percent", 10)]:
            c = save_setup(
                self.admin,
                ConcessionType(name=name, mode=mode, default_value=value, stackable=True),
            )
            r = request_action(
                self.admin,
                "discount",
                student=self.student,
                amount_value=value,
                day=DAY,
                reason="Verified fictional stackable concession",
                payload={
                    "concession_type": str(c.pk),
                    "starts_on": "2026-08-01",
                    "ends_on": "2027-07-31",
                },
            )
            decide_request(
                self.principal, r.pk, approve=True, reason="Independently approved stacking policy"
            )
        self.assertEqual(self.invoice().total, 8100)


class FinanceCashierTests(FinanceFixture, TestCase):
    def test_custom_cashier_can_land_collect_but_not_approve_or_export(self):
        from django.contrib.auth.models import Group, Permission

        from accounts.roles import CASHIER_PERMISSIONS

        from .helpers import BACKEND

        cashier = make_user("limitedcashier")
        group = Group.objects.create(name="Fictional Cashier")
        group.permissions.set(
            Permission.objects.filter(
                content_type__app_label="finance",
                codename__in=[p.split(".")[1] for p in CASHIER_PERMISSIONS],
            )
        )
        cashier.groups.add(group)
        self.client.force_login(cashier, backend=BACKEND)
        self.assertRedirects(self.client.get("/"), "/finance/")
        self.assertEqual(self.client.get("/finance/collect/").status_code, 200)
        for path in (
            "/finance/reports/?format=csv",
            "/finance/journal/",
            "/finance/setup/settings/",
        ):
            self.assertEqual(self.client.get(path).status_code, 403)
        r = request_action(
            self.accountant,
            "refund_credit",
            credit=self.payment("1000").credit_lot,
            amount_value=100,
            day=DAY,
            target_account=control("cash"),
            reason="Fictional refund for cashier boundary",
        )
        with self.assertRaises(PermissionDenied):
            decide_request(cashier, r.pk, approve=True, reason="Cashier must not approve refunds")

    def test_non_refundable_fee_cannot_be_refunded(self):
        self.category.refundable = False
        save_setup(self.admin, self.category)
        invoice = self.invoice()
        self.payment("1000", invoice)
        with self.assertRaises(ValidationError):
            self.approve(
                "refund_fee",
                invoice=invoice,
                line=invoice.lines.first(),
                amount_value=100,
                target_account=control("cash"),
            )

    def test_percent_fine_does_not_compound(self):
        from finance.fines import apply_late_fee

        invoice = self.invoice()
        self.settings.fine_mode = "percent"
        self.settings.fine_value = 1
        self.settings.fine_repeat_days = 1
        self.settings.fine_cap = 150
        save_setup(self.admin, self.settings)
        first = apply_late_fee(self.accountant, invoice.pk, day=date(2026, 10, 22))
        second = apply_late_fee(self.accountant, invoice.pk, day=DAY)
        self.assertEqual(first.amount, 100)
        self.assertEqual(second.amount, 50)
        self.assertEqual(invoice_totals(invoice)["balance"], 10150)

    def test_rejected_reconciliation_releases_reserved_lines(self):
        from finance.models import ReconciliationLine
        from finance.reconciliation import request_reconciliation

        self.payment("1000")
        line = JournalLine.objects.get(account=control("cash"))
        payload = {
            "starts_on": DAY.isoformat(),
            "ends_on": DAY.isoformat(),
            "opening": "0",
            "closing": "1000",
            "lines": [line.pk],
        }
        r = request_reconciliation(
            self.accountant, control("cash"), payload, "Fictional statement reservation"
        )
        decide_request(
            self.principal, r.pk, approve=False, reason="Statement evidence requires another review"
        )
        self.assertFalse(ReconciliationLine.objects.get(line=line).is_active)
        self.assertIsNotNone(
            request_reconciliation(
                self.accountant, control("cash"), payload, "Revised fictional statement reservation"
            )
        )

    def test_authorized_void_replacement_preserves_original(self):
        original = self.invoice()
        self.approve("void", invoice=original)
        original.refresh_from_db()
        before = original.snapshot
        self.approve("replace", invoice=original)
        replacement = Invoice.objects.get(replaces=original)
        issue_invoice(self.accountant, replacement.pk)
        original.refresh_from_db()
        self.assertEqual(original.snapshot, before)
        self.assertEqual(original.state, "voided")
        self.assertEqual(student_balances(self.student)["owed"], 10000)


class FinanceEnrollmentTests(FinanceFixture, TestCase):
    def test_transfer_prorates_class_prices_and_class_outstanding(self):
        from academics.models import SchoolClass, Section
        from finance.reporting import financial_report
        from people.models import Enrollment

        placement = Enrollment.objects.get(student=self.student, academic_year=self.data["year"])
        placement.ended_on = date(2026, 10, 15)
        placement.is_active = False
        placement.save()
        grade = SchoolClass.objects.create(name="Grade 7", sort_order=7)
        section = Section.objects.create(school_class=grade, name="A")
        Enrollment.objects.create(
            student=self.student,
            academic_year=self.data["year"],
            section=section,
            started_on=date(2026, 10, 16),
        )
        structure = save_setup(
            self.admin,
            FeeStructure(
                name="Grade 7 plan",
                academic_year=self.data["year"],
                school_class=grade,
                frequency="monthly",
                starts_on=date(2026, 8, 1),
                ends_on=date(2027, 7, 31),
            ),
        )
        save_setup(self.admin, FeeLine(structure=structure, category=self.category, amount=16000))
        invoice = self.invoice()
        self.assertEqual(invoice.total, Decimal("13096.77"))
        self.assertEqual(invoice.lines.count(), 2)
        report = financial_report(self.accountant)
        self.assertEqual(report["classes"]["Grade 6"], Decimal("4838.71"))
        self.assertEqual(report["classes"]["Grade 7"], Decimal("8258.06"))
        self.assertTrue(assert_consistent()["balanced"])
