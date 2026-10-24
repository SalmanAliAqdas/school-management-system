"""Exercise Phase 8 in installed Chrome against an owned disposable PostgreSQL database."""

import os
import secrets
import sys
import threading
import uuid
from datetime import time
from decimal import Decimal
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, make_server

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.test"


def main():
    import django

    django.setup()
    from django.conf import settings
    from django.contrib.staticfiles.handlers import StaticFilesHandler
    from django.core.wsgi import get_wsgi_application
    from django.db import connection, connections
    from django.test import override_settings
    from django.test.utils import setup_databases, teardown_databases
    from playwright.sync_api import sync_playwright

    from attendance.calendar import school_now
    from certificates.models import DocumentRequest, DocumentType, Signatory
    from certificates.services import create_request, decide, issue
    from core.models import SchoolSettings
    from finance.models import Account, FinanceSettings, FinancialPeriod, FinancialYear
    from hr.models import Department, Designation, Employee
    from hr.services import employment_change
    from inventory.models import Asset, Item, StockMovement
    from inventory.models import Category as StockCategory
    from inventory.models import Location as StockLocation
    from inventory.services import finalize
    from library.models import Book, Category, Copy, Location, Membership, Policy
    from library.services import issue as issue_book
    from payroll.models import Component, PayrollPeriod, PayrollSettings, SalaryRevision
    from payroll.services import generate, transition
    from people.models import Staff
    from tests.helpers import make_school_data, make_user
    from transport.models import Route, Stop, StudentAssignment, Trip, Vehicle
    from transport.services import assign_student, save_trip

    original = connection.settings_dict["NAME"]
    settings.DATABASES["default"].setdefault("TEST", {})["NAME"] = (
        "test_phase8_browser_" + uuid.uuid4().hex[:12]
    )
    old = setup_databases(verbosity=0, interactive=False)
    print("Phase 8 browser: disposable database ready", flush=True)
    assert connection.settings_dict["NAME"] != original
    server = thread = None
    output = ROOT / ".local/previews/phase8"
    output.mkdir(parents=True, exist_ok=True)

    class Quiet(WSGIRequestHandler):
        def log_message(self, *args):
            pass

    try:
        d = make_school_data()
        principal = make_user("phase8-principal", "Principal")
        hr_user = make_user("phase8-hr", "HR Manager")
        librarian = make_user("phase8-librarian", "Librarian")
        transport_user = make_user("phase8-transport", "Transport Manager")
        inventory_user = make_user("phase8-inventory", "Inventory Manager")
        SchoolSettings.objects.create(name="Fictional Phase 8 School")
        password = secrets.token_urlsafe(24) + "-Fictional!"
        users = [
            d["student_user"],
            d["parent"],
            principal,
            hr_user,
            librarian,
            transport_user,
            inventory_user,
        ]
        for user in users:
            user.set_password(password)
            user.save()
        today = school_now().date()
        staff = Staff.objects.create(
            user=hr_user,
            first_name="Fictional",
            last_name="Employee",
            employee_number="P8-BROWSER",
            job_title="Operations officer",
        )
        department = Department.objects.create(name="Operations", code="P8-OPS")
        designation = Designation.objects.create(department=department, title="Officer")
        employee = Employee.objects.create(user=hr_user, staff=staff, employee_code="P8-BROWSER")
        employment_change(
            hr_user,
            employee,
            department=department,
            designation=designation,
            employment_type="permanent",
            starts_on=today.replace(month=1, day=1),
        )

        FinanceSettings.objects.create(currency="PKR")
        year = FinancialYear.objects.create(
            name="Browser FY",
            starts_on=today.replace(month=1, day=1),
            ends_on=today.replace(month=12, day=31),
        )
        FinancialPeriod.objects.create(
            financial_year=year,
            name="Browser period",
            starts_on=today.replace(day=1),
            ends_on=today.replace(day=28),
        )
        expense = Account.objects.create(
            code="B-EXP", name="Salary expense", kind="expense", control="expense"
        )
        payable = Account.objects.create(
            code="B-PAY", name="Salary payable", kind="liability", control="payable"
        )
        bank = Account.objects.create(
            code="B-BANK", name="Payroll bank", kind="asset", control="bank"
        )
        PayrollSettings.objects.create(salary_payable_account=payable, payment_account=bank)
        component = Component.objects.create(
            name="Basic salary", code="BASIC", kind="earning", account=expense
        )
        SalaryRevision.objects.create(
            employee=employee,
            component=component,
            amount=Decimal("50000"),
            effective_from=year.starts_on,
            authorized_by=principal,
        )
        period = PayrollPeriod.objects.create(
            name="Browser payroll",
            starts_on=today.replace(day=1),
            ends_on=today.replace(day=28),
            payment_date=today,
        )
        run = generate(hr_user, period, [employee])
        transition(hr_user, run.pk, "submit")
        transition(principal, run.pk, "approve")
        run = transition(principal, run.pk, "finalize")
        slip = run.payslips.get()

        policy = Policy.objects.create(name="Students", borrower_kind="student")
        member = Membership.objects.create(student=d["own"], policy=policy)
        category = Category.objects.create(name="Fiction")
        library_location = Location.objects.create(name="Main library")
        book = Book.objects.create(
            title="The Fictional Garden", authors="A. Writer", category=category
        )
        copy = Copy.objects.create(
            book=book, accession_number="BROWSER-BOOK", location=library_location
        )
        issue_book(librarian, copy.pk, member.pk)

        vehicle = Vehicle.objects.create(
            identifier="BROWSER-BUS", registration="FICTIONAL-1", kind="Bus", capacity=10
        )
        route = Route.objects.create(name="Garden route")
        pickup = Stop.objects.create(route=route, name="Garden stop", sequence=1)
        school = Stop.objects.create(route=route, name="School", sequence=2)
        trip = Trip(
            route=route,
            direction="morning",
            vehicle=vehicle,
            driver=employee,
            starts_at=time(7),
            ends_at=time(8),
            effective_from=year.starts_on,
        )
        save_trip(transport_user, trip)
        assign_student(
            transport_user,
            StudentAssignment(
                student=d["own"],
                trip=trip,
                pickup_stop=pickup,
                dropoff_stop=school,
                starts_on=year.starts_on,
            ),
        )

        stock_category = StockCategory.objects.create(name="Equipment", kind="asset")
        item = Item.objects.create(
            category=stock_category, code="LAPTOP", name="Laptop", unit="each"
        )
        store = StockLocation.objects.create(name="Main store")
        movement = StockMovement.objects.create(
            reference="BROWSER-RECEIPT",
            item=item,
            kind="receipt",
            quantity=2,
            to_location=store,
            occurred_on=today,
            actor=inventory_user,
        )
        finalize(inventory_user, movement.pk)
        Asset.objects.create(
            item=item,
            identifier="BROWSER-ASSET",
            acquired_on=today,
            location=store,
            custodian=employee,
        )

        kind = DocumentType.objects.create(
            name="Enrollment certificate", audience="student", template_text="Is enrolled."
        )
        signatory = Signatory.objects.create(name="Fictional Principal", title="Principal")
        request = create_request(
            d["student_user"],
            DocumentRequest(document_type=kind, student=d["own"], purpose="School record"),
        )
        decide(principal, request.pk, True)
        document = issue(principal, request.pk, signatory)
        print("Phase 8 browser: fixtures ready", flush=True)

        with override_settings(DEBUG=True):
            server = make_server(
                "127.0.0.1", 0, StaticFilesHandler(get_wsgi_application()), handler_class=Quiet
            )
            base = f"http://127.0.0.1:{server.server_port}"

            def serve():
                try:
                    server.serve_forever()
                finally:
                    connections.close_all()

            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            errors = []
            with sync_playwright() as pw:
                browser = pw.chromium.launch(channel="chrome", headless=True)
                context = browser.new_context(viewport={"width": 1280, "height": 900})
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))

                def visit(path, status=200):
                    response = page.goto(base + path)
                    assert response.status == status, (path, response.status)

                def login(username):
                    visit("/accounts/login/")
                    page.get_by_label("Username", exact=False).fill(username)
                    page.get_by_label("Password", exact=False).fill(password)
                    page.get_by_role("button", name="Sign in to workspace").click()
                    page.wait_for_url("**/dashboard/**")

                def logout():
                    page.get_by_role("button", name="Sign out").click()

                login("phase8-hr")
                print("Phase 8 browser: employee session", flush=True)
                for path in ["/hr/", "/payroll/", "/inventory/"]:
                    visit(path)
                payslip_response = context.request.get(base + f"/payroll/payslips/{slip.pk}/")
                assert payslip_response.status == 200
                assert payslip_response.headers["content-type"] == "application/pdf"
                page.screenshot(path=str(output / "employee-services.png"), full_page=True)
                logout()
                login("phase8-librarian")
                print("Phase 8 browser: librarian session", flush=True)
                visit("/library/")
                assert page.get_by_text(book.title, exact=True).count() > 0
                logout()
                login("learner")
                print("Phase 8 browser: student session", flush=True)
                visit("/library/")
                visit("/certificates/")
                certificate_response = context.request.get(
                    base + f"/certificates/documents/{document.pk}/"
                )
                assert certificate_response.status == 200
                assert certificate_response.headers["content-type"] == "application/pdf"
                assert context.request.get(base + "/payroll/").status == 403
                logout()
                login("guardian")
                print("Phase 8 browser: guardian session", flush=True)
                visit("/transport/")
                assert page.get_by_text(d["own"].first_name, exact=False).count() > 0
                assert d["other"].first_name not in page.content()
                logout()
                login("phase8-inventory")
                print("Phase 8 browser: inventory session", flush=True)
                visit("/inventory/")
                page.set_viewport_size({"width": 390, "height": 900})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                page.screenshot(path=str(output / "inventory-mobile.png"), full_page=True)
                assert context.request.get(base + "/payroll/").status == 403
                visit(f"/certificates/verify/{document.verification_token}/")
                assert d["own"].admission_number not in page.content()
                browser.close()
            assert not errors, errors
    finally:
        if server:
            server.shutdown()
            server.server_close()
        if thread:
            thread.join(timeout=5)
        connections.close_all()
        teardown_databases(old, verbosity=0)
    print("Phase 8 Chrome QA passed on an owned disposable PostgreSQL database.")
    print(f"Screenshots: {output}")


if __name__ == "__main__":
    main()
