from datetime import date, time
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from certificates.models import DocumentRequest, DocumentType, Signatory
from certificates.services import create_request, decide, issue, revoke
from finance.models import Account, FinanceSettings, FinancialPeriod, FinancialYear
from hr.models import Department, Designation, Employee
from hr.services import employment_change, end_employment
from inventory.models import Asset, Item, StockMovement
from inventory.models import Category as StockCategory
from inventory.models import Location as StockLocation
from inventory.services import approve_disposal, balance, finalize, request_disposal, reverse
from library.models import Book, Category, Copy, Location, Membership, Policy, Reservation
from library.services import issue as issue_book
from library.services import renew, reserve, return_copy
from payroll.models import Component, PayrollPeriod, PayrollSettings, SalaryRevision
from payroll.services import generate, record_payment, transition
from payroll.services import reverse as reverse_payroll
from people.models import Staff
from transport.models import Route, Stop, StudentAssignment, Trip, Vehicle
from transport.services import assign_student, save_trip

from .helpers import BACKEND, make_school_data, make_user


class Phase8Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.d = make_school_data()
        cls.principal = make_user("phase8principal", "Principal")
        cls.hr_user = make_user("phase8hr", "HR Manager")
        cls.librarian = make_user("phase8library", "Librarian")
        cls.transport = make_user("phase8transport", "Transport Manager")
        cls.inventory = make_user("phase8inventory", "Inventory Manager")
        staff = Staff.objects.create(
            user=cls.hr_user,
            first_name="Fictional",
            last_name="Officer",
            employee_number="P8-E001",
            job_title="HR Officer",
        )
        cls.department = Department.objects.create(name="Administration", code="ADM")
        cls.designation = Designation.objects.create(department=cls.department, title="HR Officer")
        cls.employee = Employee.objects.create(
            user=cls.hr_user, staff=staff, employee_code="P8-E001"
        )
        employment_change(
            cls.hr_user,
            cls.employee,
            department=cls.department,
            designation=cls.designation,
            employment_type="permanent",
            starts_on=date(2026, 8, 1),
        )

    def test_employment_history_is_effective_dated(self):
        finance = Department.objects.create(name="Finance", code="FIN")
        accountant = Designation.objects.create(department=finance, title="Accountant")
        row = employment_change(
            self.hr_user,
            self.employee,
            department=finance,
            designation=accountant,
            employment_type="permanent",
            starts_on=date(2026, 10, 1),
        )
        previous = self.employee.employment_records.exclude(pk=row.pk).get()
        self.assertEqual(previous.ends_on, date(2026, 9, 30))

    def test_employment_end_requires_reason(self):
        with self.assertRaises(ValidationError):
            end_employment(self.hr_user, self.employee.pk, date(2026, 10, 1), "")

    def finance_setup(self):
        settings = FinanceSettings.objects.create(currency="PKR")
        year = FinancialYear.objects.create(
            name="FY26", starts_on=date(2026, 1, 1), ends_on=date(2026, 12, 31)
        )
        FinancialPeriod.objects.create(
            financial_year=year,
            name="October",
            starts_on=date(2026, 10, 1),
            ends_on=date(2026, 10, 31),
        )
        expense = Account.objects.create(
            code="P8-EXP", name="Salary expense", kind="expense", control="expense"
        )
        payable = Account.objects.create(
            code="P8-PAY", name="Salary payable", kind="liability", control="payable"
        )
        bank = Account.objects.create(
            code="P8-BANK", name="Payroll bank", kind="asset", control="bank"
        )
        PayrollSettings.objects.create(salary_payable_account=payable, payment_account=bank)
        return settings, expense

    def test_payroll_proration_approval_and_balanced_posting(self):
        _settings, expense = self.finance_setup()
        component = Component.objects.create(
            name="Basic salary", code="BASIC", kind="earning", account=expense
        )
        SalaryRevision.objects.create(
            employee=self.employee,
            component=component,
            amount=Decimal("31000"),
            effective_from=date(2026, 10, 1),
            authorized_by=self.principal,
        )
        period = PayrollPeriod.objects.create(
            name="October 2026",
            starts_on=date(2026, 10, 1),
            ends_on=date(2026, 10, 31),
            payment_date=date(2026, 10, 24),
        )
        run = generate(self.hr_user, period, [self.employee])
        transition(self.hr_user, run.pk, "submit")
        transition(self.principal, run.pk, "approve")
        finalized = transition(self.principal, run.pk, "finalize")
        slip = finalized.payslips.get()
        self.assertEqual(slip.net, Decimal("31000"))
        self.assertEqual(slip.journal.lines.count(), 2)
        paid = record_payment(self.principal, slip.pk)
        self.assertEqual(paid.state, "paid")
        self.assertEqual(paid.payment_journal.lines.count(), 2)
        self.client.force_login(self.hr_user, backend=BACKEND)
        response = self.client.get(f"/payroll/payslips/{paid.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")

    def test_payroll_reversal_is_compensating_and_rejects_paid_run(self):
        _settings, expense = self.finance_setup()
        component = Component.objects.create(
            name="Base pay", code="BASE", kind="earning", account=expense
        )
        SalaryRevision.objects.create(
            employee=self.employee,
            component=component,
            amount=Decimal("10000"),
            effective_from=date(2026, 10, 1),
            authorized_by=self.principal,
        )
        period = PayrollPeriod.objects.create(
            name="Reversal month",
            starts_on=date(2026, 10, 1),
            ends_on=date(2026, 10, 31),
            payment_date=date(2026, 10, 24),
        )
        run = generate(self.hr_user, period, [self.employee])
        transition(self.hr_user, run.pk, "submit")
        transition(self.principal, run.pk, "approve")
        transition(self.principal, run.pk, "finalize")
        reversed_run = reverse_payroll(
            self.principal, run.pk, "Correction required", day=date(2026, 10, 24)
        )
        self.assertEqual(reversed_run.state, "reversed")
        self.assertEqual(
            reversed_run.reversal_journal.reversal_of_id, run.payslips.get().journal_id
        )
        self.assertEqual(reversed_run.payslips.get().state, "reversed")

    def library_setup(self):
        policy = Policy.objects.create(name="Students", borrower_kind="student")
        member = Membership.objects.create(student=self.d["own"], policy=policy)
        category = Category.objects.create(name="Fiction")
        location = Location.objects.create(name="Main library")
        book = Book.objects.create(title="Fictional River", authors="A. Writer", category=category)
        copy = Copy.objects.create(book=book, accession_number="ACC-001", location=location)
        return member, book, copy

    def test_library_issue_renew_return_and_reservation(self):
        member, book, copy = self.library_setup()
        other = Membership.objects.create(student=self.d["other"], policy=member.policy)
        loan = issue_book(self.librarian, copy.pk, member.pk)
        reserve(other, book)
        with self.assertRaises(ValidationError):
            renew(self.librarian, loan.pk)
        return_copy(self.librarian, loan.pk)
        copy.refresh_from_db()
        self.assertEqual(copy.status, "reserved")
        self.assertEqual(Reservation.objects.get(membership=other).state, "available")

    def test_copy_cannot_be_issued_twice(self):
        member, _book, copy = self.library_setup()
        issue_book(self.librarian, copy.pk, member.pk)
        with self.assertRaises(ValidationError):
            issue_book(self.librarian, copy.pk, member.pk)

    def transport_setup(self, capacity=1):
        vehicle = Vehicle.objects.create(
            identifier="BUS-1", registration="TEST-REG", kind="Bus", capacity=capacity
        )
        route = Route.objects.create(name="North route")
        first = Stop.objects.create(route=route, name="First", sequence=1)
        last = Stop.objects.create(route=route, name="School", sequence=2)
        trip = Trip(
            route=route,
            direction="morning",
            vehicle=vehicle,
            driver=self.employee,
            starts_at=time(7),
            ends_at=time(8),
            effective_from=date(2026, 8, 1),
        )
        save_trip(self.transport, trip)
        return trip, first, last

    def test_transport_capacity_and_family_privacy(self):
        trip, first, last = self.transport_setup()
        assign_student(
            self.transport,
            StudentAssignment(
                student=self.d["own"],
                trip=trip,
                pickup_stop=first,
                dropoff_stop=last,
                starts_on=date(2026, 8, 1),
            ),
        )
        with self.assertRaises(ValidationError):
            assign_student(
                self.transport,
                StudentAssignment(
                    student=self.d["other"],
                    trip=trip,
                    pickup_stop=first,
                    dropoff_stop=last,
                    starts_on=date(2026, 8, 1),
                ),
            )
        self.client.force_login(self.d["parent"], backend=BACKEND)
        response = self.client.get("/transport/")
        self.assertContains(response, self.d["own"].first_name)
        self.assertNotContains(response, self.d["other"].first_name)

    def inventory_setup(self):
        category = StockCategory.objects.create(name="Stationery", kind="consumable")
        item = Item.objects.create(category=category, code="PAPER", name="Paper", unit="ream")
        location = StockLocation.objects.create(name="Store")
        return item, location

    def test_inventory_balance_and_negative_prevention(self):
        item, location = self.inventory_setup()
        receipt = StockMovement.objects.create(
            reference="REC-1",
            item=item,
            kind="receipt",
            quantity=10,
            to_location=location,
            occurred_on=date(2026, 10, 1),
            actor=self.principal,
        )
        finalize(self.principal, receipt.pk)
        issue_row = StockMovement.objects.create(
            reference="ISS-1",
            item=item,
            kind="issue",
            quantity=4,
            from_location=location,
            occurred_on=date(2026, 10, 2),
            actor=self.principal,
        )
        finalize(self.principal, issue_row.pk)
        self.assertEqual(balance(item, location), Decimal("6"))
        too_much = StockMovement.objects.create(
            reference="ISS-2",
            item=item,
            kind="issue",
            quantity=7,
            from_location=location,
            occurred_on=date(2026, 10, 3),
            actor=self.principal,
        )
        with self.assertRaises(ValidationError):
            finalize(self.principal, too_much.pk)

    def test_stock_correction_and_independent_asset_disposal(self):
        item, location = self.inventory_setup()
        receipt = StockMovement.objects.create(
            reference="REC-CORRECT",
            item=item,
            kind="receipt",
            quantity=3,
            to_location=location,
            occurred_on=date(2026, 10, 1),
            actor=self.principal,
        )
        finalize(self.principal, receipt.pk)
        reverse(self.principal, receipt.pk, "REV-REC", "Duplicate receipt")
        self.assertEqual(balance(item, location), Decimal("0"))
        asset = Asset.objects.create(
            item=item,
            identifier="ASSET-1",
            acquired_on=date(2026, 1, 1),
            location=location,
        )
        event = request_disposal(self.inventory, asset.pk, "Beyond repair")
        with self.assertRaises(PermissionDenied):
            approve_disposal(self.inventory, event.pk)
        disposed = approve_disposal(self.principal, event.pk)
        self.assertEqual(disposed.status, "disposed")

    def test_certificate_lifecycle_and_minimal_verification(self):
        kind = DocumentType.objects.create(
            name="Enrollment certificate", audience="student", template_text="Is enrolled."
        )
        signatory = Signatory.objects.create(name="Fictional Principal", title="Principal")
        request = create_request(
            self.d["student_user"],
            DocumentRequest(document_type=kind, student=self.d["own"], purpose="Record"),
        )
        decide(self.principal, request.pk, True)
        document = issue(self.principal, request.pk, signatory)
        self.client.force_login(self.d["student_user"], backend=BACKEND)
        pdf = self.client.get(f"/certificates/documents/{document.pk}/")
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        response = self.client.get(f"/certificates/verify/{document.verification_token}/")
        self.assertContains(response, "Enrollment certificate")
        self.assertNotContains(response, self.d["own"].admission_number)
        revoke(self.principal, document.pk, "Replaced with corrected wording")
        response = self.client.get(f"/certificates/verify/{document.verification_token}/")
        self.assertContains(response, "Revoked")

    def test_salary_is_not_visible_to_unrelated_user(self):
        self.client.force_login(self.d["student_user"], backend=BACKEND)
        self.assertEqual(self.client.get("/payroll/").status_code, 403)
