"""Verify Phase 9 analytics in Chrome against an owned disposable PostgreSQL database."""

import os
import secrets
import sys
import threading
import uuid
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

    from core.models import SchoolSettings
    from tests.helpers import make_school_data, make_user

    original = connection.settings_dict["NAME"]
    settings.DATABASES["default"].setdefault("TEST", {})["NAME"] = (
        "test_phase9_browser_" + uuid.uuid4().hex[:12]
    )
    old = setup_databases(verbosity=0, interactive=False)
    assert connection.settings_dict["NAME"] != original
    server = thread = None
    output = ROOT / ".local/previews/phase9"
    output.mkdir(parents=True, exist_ok=True)

    class Quiet(WSGIRequestHandler):
        def log_message(self, *args):
            pass

    try:
        d = make_school_data()
        admin = make_user("phase9-admin", "System Administrator")
        principal = make_user("phase9-principal", "Principal")
        demo = make_user("demo.analytics", "System Administrator")
        SchoolSettings.objects.create(name="Fictional Analytics School")
        password = secrets.token_urlsafe(24) + "-Fictional!"
        for user in [admin, principal, demo, d["student_user"], d["parent"]]:
            user.set_password(password)
            user.save()

        with override_settings(DEBUG=True, ALLOW_DEMO_DATA=True):
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
                context = browser.new_context(viewport={"width": 1440, "height": 1000})
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "console",
                    lambda message: (
                        errors.append(message.text) if message.type == "error" else None
                    ),
                )

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

                query = (
                    f"?academic_year={d['year'].pk}&starts_on={d['year'].starts_on}"
                    f"&ends_on={d['year'].ends_on}"
                )
                login("phase9-admin")
                visit("/analytics/" + query)
                assert page.get_by_text("2", exact=True).count() > 0
                assert page.get_by_text("No finalized data", exact=True).count() > 0
                assert page.get_by_text("Cash collections", exact=True).count() == 1
                page.screenshot(path=str(output / "executive-dashboard.png"), full_page=True)
                visit("/analytics/reports/")
                visit("/analytics/reports/students/" + query)
                export = context.request.get(
                    base + "/analytics/reports/students/" + query + "&format=csv"
                )
                assert export.status == 200 and "text/csv" in export.headers["content-type"]
                visit(f"/analytics/students/{d['own'].pk}/")
                visit("/payroll/")
                logout()

                login("learner")
                visit(f"/analytics/students/{d['own'].pk}/")
                assert context.request.get(base + "/payroll/").status == 403
                logout()

                login("guardian")
                visit(f"/analytics/students/{d['own'].pk}/")
                assert (
                    context.request.get(base + f"/analytics/students/{d['other'].pk}/").status
                    == 404
                )
                logout()

                login("demo.analytics")
                visit("/demo/guide/")
                visit("/analytics/" + query)
                for width in (768, 390, 320):
                    page.set_viewport_size({"width": width, "height": 900})
                    assert page.evaluate(
                        "document.documentElement.scrollWidth <= window.innerWidth"
                    )
                page.get_by_role("button", name="Open navigation").focus()
                page.keyboard.press("Enter")
                assert (
                    page.get_by_role("button", name="Open navigation").get_attribute(
                        "aria-expanded"
                    )
                    == "true"
                )
                page.keyboard.press("Escape")
                page.screenshot(path=str(output / "executive-mobile.png"), full_page=True)
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
    print("Phase 9 Chrome QA passed on an owned disposable PostgreSQL database.")
    print(f"Screenshots: {output}")


if __name__ == "__main__":
    main()
