"""Exercise attendance workflows in a newly created, disposable PostgreSQL database.

Uses installed Chrome and local static assets. Never serves the application database.
Passwords are generated in memory and never printed or passed on command lines.
"""

import io
import os
import secrets
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
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
    from django.contrib.staticfiles.handlers import StaticFilesHandler
    from django.core.management import call_command
    from django.core.wsgi import get_wsgi_application
    from django.db import connection, connections
    from django.test import override_settings
    from django.test.utils import setup_databases, teardown_databases
    from playwright.sync_api import sync_playwright

    from academics.models import AcademicYear, Section
    from attendance.calendar import SchoolCalendar, school_now
    from attendance.models import AttendanceCorrection, LeaveRequest, StudentAttendance
    from people.models import Student, Teacher

    original_name = connection.settings_dict["NAME"]
    settings.DATABASES["default"].setdefault("TEST", {})["NAME"] = (
        f"test_attendance_browser_{uuid.uuid4().hex[:12]}"
    )
    old_config = setup_databases(verbosity=0, interactive=False)
    if connection.settings_dict["NAME"] == original_name:
        raise RuntimeError("Browser QA requires an isolated test database.")
    server = thread = None
    output = ROOT / ".local" / "previews" / "attendance"
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
            year = AcademicYear.objects.get(name="2026–2027")
            today = school_now().date()
            calendar = SchoolCalendar(year)
            if calendar.reason(today):
                raise RuntimeError("Run this browser workflow on a configured working school date.")
            section = Section.objects.get(school_class__name="Grade 8", name="A")
            child = Student.objects.get(admission_number="DEMO-0001")
            other = Student.objects.exclude(pk=child.pk).first()
            teacher = Teacher.objects.get(employee_number="DEMO-T001")
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

            def db_read(callback):
                def worker():
                    try:
                        return callback()
                    finally:
                        connections.close_all()

                with ThreadPoolExecutor(max_workers=1) as pool:
                    return pool.submit(worker).result(timeout=10)

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
                    page.wait_for_url("**/dashboard/**")

                def logout():
                    page.get_by_role("button", name="Sign out").click()
                    page.wait_for_url("**/accounts/login/")

                login("demo.admin")
                assert page.goto(f"{base}/attendance/").status == 200
                assert page.locator("#attendance-daily-chart").evaluate(
                    "el => !!Chart.getChart(el)"
                )
                routes = [
                    ("/attendance/", "dashboard"),
                    (
                        f"/attendance/register/?academic_year={year.pk}&section={section.pk}&date={today}",
                        "register",
                    ),
                    (f"/attendance/students/{child.pk}/", "student-calendar"),
                    ("/attendance/staff/", "staff-dashboard"),
                    ("/attendance/corrections/", "corrections"),
                    ("/attendance/leave/", "leave"),
                    ("/attendance/settings/", "policy-calendar"),
                    ("/attendance/reports/classes/", "reports"),
                ]
                for route, name in routes:
                    assert page.goto(base + route).status == 200
                    page.screenshot(path=str(output / f"{name}-desktop.png"), full_page=True)
                    page.set_viewport_size({"width": 390, "height": 844})
                    page.wait_for_timeout(400)
                    page.screenshot(path=str(output / f"{name}-mobile.png"), full_page=True)
                    assert page.evaluate(
                        "document.documentElement.scrollWidth <= window.innerWidth"
                    ), route
                    page.set_viewport_size({"width": 1440, "height": 1100})
                page.goto(
                    f"{base}/attendance/register/?academic_year={year.pk}&section={section.pk}&date={today}"
                )
                page.get_by_role("button", name="Mark All Present", exact=True).click()
                assert page.locator('select[name$="-status"]').evaluate_all(
                    "els => els.every(el => el.value === 'present')"
                )
                page.get_by_role("button", name="Save draft", exact=True).click()
                assert page.get_by_text("Attendance draft saved.", exact=True).is_visible()
                page.get_by_label("I have reviewed every row", exact=False).check()
                page.get_by_label("Late submission reason", exact=False).fill(
                    "Isolated fictional browser QA"
                )
                page.get_by_role("button", name="Finalize register", exact=True).click()
                assert page.get_by_text("Previously finalized attendance", exact=True).is_visible()
                entry_pk = db_read(
                    lambda: (
                        StudentAttendance.objects.filter(
                            register__section=section, attendance_on=today
                        )
                        .values_list("pk", flat=True)
                        .first()
                    )
                )
                page.goto(f"{base}/attendance/corrections/student/{entry_pk}/request/")
                page.get_by_label("Status", exact=False).select_option("absent")
                page.get_by_label("Reason", exact=False).fill(
                    "Browser QA: reviewed classroom record"
                )
                page.get_by_role("button", name="Confirm and save", exact=True).click()
                correction_pk = db_read(
                    lambda: AttendanceCorrection.objects.values_list("pk", flat=True).get(
                        reason="Browser QA: reviewed classroom record"
                    )
                )
                logout()
                login("demo.principal")
                page.goto(f"{base}/attendance/corrections/{correction_pk}/review/")
                page.locator("#id_decision").select_option("approve")
                page.get_by_label("I confirm this decision", exact=False).check()
                page.get_by_role("button", name="Confirm and save", exact=True).click()
                entry = db_read(
                    lambda: StudentAttendance.objects.values("status", "revision").get(pk=entry_pk)
                )
                assert entry["status"] == "absent" and entry["revision"] == 1
                for kind in ("csv", "pdf"):
                    response = context.request.get(
                        f"{base}/attendance/reports/students/?academic_year={year.pk}&period=year&format={kind}"
                    )
                    assert response.status == 200
                    if kind == "pdf":
                        assert response.body().startswith(b"%PDF-")
                logout()
                login("demo.teacher")
                assert context.request.get(
                    f"{base}/attendance/register/?academic_year={year.pk}&section={section.pk}&date={today}"
                ).status in (200, 403)
                assert page.goto(f"{base}/attendance/employees/teacher/{teacher.pk}/").status == 200
                page.goto(f"{base}/attendance/leave/new/")
                next_day = today + timedelta(days=3)
                page.get_by_label("Academic year", exact=False).select_option(str(year.pk))
                page.get_by_label("Person", exact=False).select_option(f"teacher:{teacher.pk}")
                page.get_by_label("Starts on", exact=False).fill(next_day.isoformat())
                page.get_by_label("Ends on", exact=False).fill(next_day.isoformat())
                page.get_by_label("Kind", exact=False).select_option("sick")
                page.get_by_label("Reason", exact=False).fill(
                    "Browser QA: fictional employee leave"
                )
                page.get_by_role("button", name="Confirm and save", exact=True).click()
                leave_pk = db_read(
                    lambda: LeaveRequest.objects.values_list("pk", flat=True).get(
                        reason="Browser QA: fictional employee leave"
                    )
                )
                logout()
                login("demo.principal")
                page.goto(f"{base}/attendance/leave/{leave_pk}/review/")
                page.locator("#id_decision").select_option("approve")
                page.get_by_label("I confirm this decision", exact=False).check()
                page.get_by_role("button", name="Confirm and save", exact=True).click()
                assert (
                    db_read(
                        lambda: LeaveRequest.objects.values_list("state", flat=True).get(
                            pk=leave_pk
                        )
                    )
                    == "approved"
                )
                logout()
                login("demo.parent")
                assert page.goto(f"{base}/attendance/notifications/").status == 200
                assert page.get_by_role("heading", name="Noor Meadow", exact=False).count() > 0
                assert context.request.get(f"{base}/attendance/students/{other.pk}/").status == 404
                logout()
                login("demo.student")
                assert page.goto(f"{base}/attendance/students/{child.pk}/").status == 200
                response = context.request.get(
                    f"{base}/attendance/reports/students/?academic_year={year.pk}&period=year&format=csv"
                )
                assert response.status == 200 and b"DEMO-0002" not in response.body()
                assert context.request.get(f"{base}/attendance/students/{other.pk}/").status == 404
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
        "Attendance browser QA passed: four roles, draft/final register, bulk present, "
        "correction review, leave review, guardian isolation, CSV/PDF "
        "and eight responsive screens."
    )
    print(f"Screenshots: {output}")


if __name__ == "__main__":
    main()
