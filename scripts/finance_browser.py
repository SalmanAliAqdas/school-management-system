"""Exercise Phase 5 in a uniquely named disposable PostgreSQL database, using Chrome.

Never serves or resets the application database. Generated fixture credentials remain
in memory, and only this script's isolated test database is removed on completion.
"""

import io
import os
import re
import secrets
import sys
import threading
import uuid
from pathlib import Path
from unittest.mock import patch
from wsgiref.simple_server import WSGIRequestHandler, make_server

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.test"


def main():
    import django

    django.setup()
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group, Permission
    from django.contrib.staticfiles.handlers import StaticFilesHandler
    from django.core.management import call_command
    from django.core.wsgi import get_wsgi_application
    from django.db import connection, connections
    from django.test import override_settings
    from django.test.utils import setup_databases, teardown_databases
    from playwright.sync_api import sync_playwright

    from accounts.roles import CASHIER_PERMISSIONS
    from finance.common import control
    from finance.models import Invoice
    from people.models import Student

    original_name = connection.settings_dict["NAME"]
    settings.DATABASES["default"].setdefault("TEST", {})["NAME"] = (
        f"test_finance_browser_{uuid.uuid4().hex[:12]}"
    )
    old_config = setup_databases(verbosity=0, interactive=False)
    if connection.settings_dict["NAME"] == original_name:
        raise RuntimeError("Browser QA requires an isolated test database.")
    server = thread = None
    output = ROOT / ".local" / "previews" / "finance"
    output.mkdir(parents=True, exist_ok=True)
    password = secrets.token_urlsafe(28) + "-Fictional!"

    class QuietHandler(WSGIRequestHandler):
        def log_message(self, format, *args):
            pass

    try:
        with (
            override_settings(DEBUG=True, ALLOW_DEMO_DATA=True),
            patch.dict(os.environ, {"DEMO_PASSWORD": password}),
        ):
            call_command("seed_demo", stdout=io.StringIO())
            clerk_group = Group.objects.create(name="Demo Cashier")
            clerk_group.permissions.set(
                Permission.objects.filter(
                    content_type__app_label="finance",
                    codename__in=[p.split(".")[1] for p in CASHIER_PERMISSIONS],
                )
            )
            cashier = get_user_model().objects.create_user(
                "demo.cashier", password=password, email="cashier@example.invalid"
            )
            cashier.groups.add(clerk_group)
            revenue_id = str(control("revenue").pk)
            cash_id = str(control("cash").pk)
            child = Student.objects.get(admission_number="DEMO-0001")
            invoice = Invoice.objects.get(student__admission_number="DEMO-0005")
            other_invoice = invoice.pk
            child_invoice = Invoice.objects.get(student=child).pk
            server = make_server(
                "127.0.0.1",
                0,
                StaticFilesHandler(get_wsgi_application()),
                handler_class=QuietHandler,
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
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="chrome", headless=True)
                context = browser.new_context(
                    viewport={"width": 1440, "height": 1100}, reduced_motion="reduce"
                )
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("dialog", lambda dialog: dialog.accept())

                def login(username):
                    page.goto(f"{base}/accounts/login/")
                    page.get_by_label("Username", exact=False).fill(username)
                    page.get_by_label("Password", exact=False).fill(password)
                    page.get_by_role("button", name="Sign in to workspace").click()
                    page.wait_for_url(
                        "**/finance/" if username == "demo.cashier" else "**/dashboard/**"
                    )

                def logout():
                    page.get_by_role("button", name="Sign out", exact=True).click()
                    page.wait_for_url("**/accounts/login/")

                def save():
                    page.get_by_role("button", name="Confirm and save", exact=True).click()
                    assert page.locator(".field-error,.alert-danger").count() == 0, page.locator(
                        "main"
                    ).inner_text()

                def screenshot(url, name):
                    assert page.goto(base + url).status == 200
                    page.screenshot(path=str(output / f"{name}.png"), full_page=True)
                    assert page.evaluate(
                        "document.documentElement.scrollWidth <= window.innerWidth"
                    ), name

                login("demo.admin")
                page.goto(base + "/finance/setup/categories/new/")
                page.get_by_label(re.compile(r"^Name\s*\*?$")).fill("Browser QA activity fee")
                page.get_by_label(re.compile(r"^Income\ account\s*\*?$")).select_option(revenue_id)
                page.get_by_label(re.compile(r"^Starts\ on\s*\*?$")).fill("2026-08-01")
                save()
                assert page.url.endswith("/finance/setup/categories/")
                page.goto(base + "/finance/setup/cycles/new/")
                page.get_by_label(re.compile(r"^Academic year")).select_option(
                    label="2026\u20132027"
                )
                page.get_by_label(re.compile(r"^Name")).fill("Browser September")
                page.get_by_label(re.compile(r"^Frequency")).select_option("monthly")
                for name, value in [
                    ("Starts on", "2026-09-01"),
                    ("Ends on", "2026-09-30"),
                    ("Issue on", "2026-09-01"),
                    ("Due on", "2026-09-10"),
                ]:
                    page.get_by_label(re.compile("^" + name)).fill(value)
                save()
                screenshot("/finance/", "admin-overview")
                page.goto(base + "/finance/requests/new/?kind=discount")
                page.get_by_label(re.compile(r"^Student\s*\*?$")).select_option(str(child.pk))
                page.get_by_label(re.compile(r"^Amount\ /\ concession\ value\s*\*?$")).fill("100")
                page.get_by_label(re.compile(r"^Concession\ type\s*\*?$")).select_option(
                    label="DEMO Sibling concession"
                )
                page.get_by_label(re.compile(r"^Starts\ on\s*\*?$")).fill("2026-11-01")
                page.get_by_label(re.compile(r"^Ends\ on\s*\*?$")).fill("2027-07-31")
                page.get_by_label(re.compile(r"^Reason\s*\*?$")).fill(
                    "Browser fictional eligibility verified"
                )
                save()
                concession_url = page.url
                logout()
                login("demo.principal")
                page.goto(concession_url)
                page.get_by_label(re.compile(r"^Reason\s*\*?$")).fill(
                    "Browser independent concession approval"
                )
                page.get_by_role("button", name="Confirm decision", exact=True).click()
                assert "Approved" in page.locator("main").inner_text()
                logout()
                login("demo.accountant")
                screenshot("/finance/billing/", "accountant-billing")
                cycle_option = (
                    page.get_by_label("Cycle", exact=False)
                    .locator("option")
                    .filter(has_text="Browser September")
                    .first
                )
                page.get_by_label("Cycle", exact=False).select_option(
                    cycle_option.get_attribute("value")
                )
                page.get_by_label("School class", exact=False).select_option(label="Grade 6")
                page.get_by_role("button", name="Preview / confirm selected batch").click()
                assert "Calculated preview" in page.locator("main").inner_text()
                page.get_by_label("Confirm this reviewed billing batch", exact=False).check()
                page.get_by_role("button", name="Preview / confirm selected batch").click()
                assert page.url.endswith("/finance/invoices/")
                page.locator("tr").filter(has_text="Browser September").first.get_by_role(
                    "link"
                ).first.click()
                generated_invoice_url = page.url
                page.get_by_role("button", name="Request independent approval").click()
                logout()
                login("demo.principal")
                page.goto(base + "/finance/requests/?state=pending")
                page.get_by_role("link", name="Invoice approval", exact=True).first.click()
                page.get_by_label(re.compile(r"^Reason")).fill(
                    "Browser independently verified invoice approval"
                )
                page.get_by_role("button", name="Confirm decision").click()
                logout()
                login("demo.accountant")
                page.goto(generated_invoice_url)
                page.get_by_role("button", name="Issue invoice", exact=True).click()
                assert page.get_by_role("link", name="Download PDF", exact=True).is_visible()
                page.goto(base + "/finance/expenses/new/")
                page.get_by_label(re.compile(r"^Category")).select_option(
                    label="DEMO Classroom supplies"
                )
                page.get_by_label(re.compile(r"^Payee")).fill("Browser Fictional Supplies")
                page.get_by_label(re.compile(r"^Value")).fill("100")
                page.get_by_label(re.compile(r"^Description")).fill(
                    "Browser fictional classroom supplies expense"
                )
                save()
                logout()
                login("demo.principal")
                page.goto(base + "/finance/requests/?state=pending")
                page.get_by_role("link", name="Expense approval", exact=True).first.click()
                page.get_by_label(re.compile(r"^Reason")).fill(
                    "Browser independent expense authorization"
                )
                page.get_by_role("button", name="Confirm decision").click()
                logout()
                login("demo.accountant")
                page.goto(base + "/finance/expenses/")
                page.locator("tr").filter(has_text="Browser Fictional Supplies").get_by_role(
                    "link", name="Record payment"
                ).click()
                page.get_by_label(re.compile(r"^Account")).select_option(cash_id)
                page.get_by_label(re.compile(r"^Reference")).fill("BROWSER-EXPENSE-001")
                save()

                screenshot("/finance/reports/", "accountant-reports")
                response = context.request.get(base + "/finance/reports/?format=pdf")
                assert response.status == 200 and response.body().startswith(b"%PDF-")
                page.goto(base + "/finance/requests/new/?kind=refund_credit")
                credit_option = (
                    page.get_by_label(re.compile(r"^Credit\s*\*?$"))
                    .locator("option")
                    .filter(has_text="Arin Cedar")
                    .first
                )
                page.get_by_label(re.compile(r"^Credit\s*\*?$")).select_option(
                    credit_option.get_attribute("value")
                )
                page.get_by_label(re.compile(r"^Amount\ /\ concession\ value\s*\*?$")).fill("100")
                page.get_by_label(re.compile(r"^Target\ account\s*\*?$")).select_option(cash_id)
                page.get_by_label(re.compile(r"^Reason\s*\*?$")).fill(
                    "Browser verified excess credit refund"
                )
                save()
                refund_url = page.url
                logout()
                login("demo.principal")
                page.goto(refund_url)
                page.get_by_label(re.compile(r"^Reason\s*\*?$")).fill(
                    "Browser independently approved credit return"
                )
                page.get_by_role("button", name="Confirm decision", exact=True).click()
                assert "Approved" in page.locator("main").inner_text()
                logout()
                login("demo.cashier")
                page.goto(base + "/finance/collect/")
                page.get_by_label(re.compile(r"^Student\s*\*?$")).select_option(
                    str(invoice.student_id)
                )
                page.get_by_label(re.compile(r"^Amount\ received\s*\*?$")).fill("1000")
                page.get_by_label(re.compile(r"^Method\s*\*?$")).select_option(
                    label="DEMO Cash, manual"
                )
                page.get_by_label(re.compile(r"^Reference\s*\*?$")).fill("BROWSER-CASH-001")
                page.get_by_label(re.compile(r"^Invoice\s*\*?$")).select_option(str(invoice.pk))
                page.get_by_label(re.compile(r"^Allocated\ amount\s*\*?$")).fill("1000")
                save()
                assert "/finance/receipts/" in page.url
                receipt_url = page.url
                assert "1,000.00" in page.locator("main").inner_text()
                response = context.request.get(receipt_url + "?format=pdf")
                assert response.status == 200 and response.body().startswith(b"%PDF-")
                page.get_by_role("button", name="Print receipt").click()
                page.screenshot(path=str(output / "cashier-receipt.png"), full_page=True)
                for path in (
                    "/finance/setup/accounts/",
                    "/finance/reports/?format=csv",
                    "/finance/journal/",
                ):
                    assert context.request.get(base + path).status == 403, path
                logout()
                login("demo.student")
                screenshot("/finance/", "student-accounts")
                assert page.goto(f"{base}/finance/invoices/{child_invoice}/").status == 200
                assert (
                    context.request.get(
                        f"{base}/finance/invoices/{other_invoice}/?format=pdf"
                    ).status
                    == 404
                )
                assert context.request.get(base + "/finance/collect/").status == 403
                logout()
                login("demo.parent")
                screenshot("/finance/", "guardian-accounts")
                assert page.goto(f"{base}/finance/invoices/{child_invoice}/").status == 200
                assert (
                    context.request.get(f"{base}/finance/invoices/{other_invoice}/").status == 404
                )
                context.set_default_timeout(10000)
                page.set_viewport_size({"width": 390, "height": 844})
                screenshot(f"/finance/students/{child.pk}/", "guardian-mobile")
                browser.close()
            if errors:
                raise AssertionError("Browser JavaScript errors: " + "; ".join(errors))
    finally:
        if server:
            server.shutdown()
            server.server_close()
        if thread:
            thread.join(timeout=5)
        connections.close_all()
        teardown_databases(old_config, verbosity=0)
    print(
        "Finance Chrome QA passed: admin fee setup, invoice generation/approval/issue, "
        "expense approval/payment, "
        "accountant billing/reports, cashier partial collection/receipt/PDF/print, "
        "student and guardian isolation, unauthorized exports and mobile layout."
    )
    print(f"Screenshots: {output}")


if __name__ == "__main__":
    main()
