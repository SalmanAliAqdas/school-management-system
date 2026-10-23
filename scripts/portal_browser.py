"""Verify Phase 6 journeys using installed Chrome and an owned disposable database."""

import io
import os
import secrets
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
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

    from academics.models import TeachingAssignment
    from attendance.models import StudentRegister
    from examinations.models import MarkSheet, PublishedResult
    from people.models import GuardianStudent, Student

    original = connection.settings_dict["NAME"]
    settings.DATABASES["default"].setdefault("TEST", {})["NAME"] = (
        f"test_portals_browser_{uuid.uuid4().hex[:12]}"
    )
    old_config = setup_databases(verbosity=0, interactive=False)
    if connection.settings_dict["NAME"] == original:
        raise RuntimeError("Browser verification requires an isolated test database.")
    output = ROOT / ".local" / "previews" / "portals"
    output.mkdir(parents=True, exist_ok=True)
    password = secrets.token_urlsafe(28) + "-Fictional!"
    server = thread = None

    class QuietHandler(WSGIRequestHandler):
        def log_message(self, format, *args):
            pass

    def db_read(callback):
        def worker():
            try:
                return callback()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(worker).result(timeout=15)

    try:
        with (
            override_settings(DEBUG=True, ALLOW_DEMO_DATA=True),
            patch.dict(os.environ, {"DEMO_PASSWORD": password}),
        ):
            call_command("seed_demo", stdout=io.StringIO())
            child = Student.objects.get(admission_number="DEMO-0001")
            sibling = Student.objects.get(admission_number="DEMO-0002")
            unrelated = Student.objects.get(admission_number="DEMO-0003")
            report = PublishedResult.objects.filter(candidate__student=child).first()
            draft = StudentRegister.objects.filter(state="draft").first()
            assignment = TeachingAssignment.objects.get(
                teacher__user__username="demo.teacher",
                academic_year=draft.academic_year,
                section=draft.section,
            )
            sheet = MarkSheet.objects.filter(
                state="draft",
                assessment__max_marks=100,
                assessment__exam_subject__cohort__session__state="open",
                assessment__exam_subject__cohort__section=assignment.section,
            ).first()
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
                page.on(
                    "console",
                    lambda message: (
                        errors.append(message.text) if message.type == "error" else None
                    ),
                )

                def login(username):
                    page.goto(base + "/accounts/login/")
                    page.get_by_label("Username", exact=False).fill(username)
                    page.get_by_label("Password", exact=False).fill(password)
                    page.get_by_role("button", name="Sign in to workspace").click()
                    page.wait_for_url("**/dashboard/**")

                def logout():
                    page.get_by_role("button", name="Sign out").click()
                    page.wait_for_url("**/accounts/login/")

                def visit(path, name):
                    response = page.goto(base + path)
                    assert response.status == 200, (path, response.status)
                    assert page.locator("h1").count() == 1
                    page.screenshot(path=str(output / f"{name}.png"), full_page=True)

                login("demo.student")
                visit("/portals/student/", "student-overview")
                visit(f"/portals/student/students/{child.pk}/attendance/", "student-attendance")
                visit(f"/portals/student/students/{child.pk}/results/", "student-results")
                assert page.locator("#academic-progress").evaluate("el => !!Chart.getChart(el)")
                visit(f"/examinations/reports/{report.pk}/", "student-report")
                response = context.request.get(
                    f"{base}/examinations/reports/{report.pk}/?format=pdf"
                )
                assert response.status == 200 and response.body().startswith(b"%PDF-")
                visit(f"/portals/student/students/{child.pk}/fees/", "student-fees")
                assert (
                    context.request.get(
                        f"{base}/portals/student/students/{unrelated.pk}/profile/"
                    ).status
                    == 404
                )
                logout()
                login("demo.parent")
                visit("/portals/parent/", "guardian-overview")
                for current in (child, sibling):
                    visit(
                        f"/portals/parent/students/{current.pk}/results/",
                        f"guardian-{current.admission_number}-results",
                    )
                    visit(
                        f"/portals/parent/students/{current.pk}/fees/",
                        f"guardian-{current.admission_number}-fees",
                    )
                page.get_by_label("View child").select_option(str(child.pk))
                page.get_by_role("button", name="Open", exact=True).click()
                page.wait_for_url(f"**/students/{child.pk}/fees/")
                visit("/portals/notifications/", "guardian-inbox")
                if page.get_by_role("button", name="Mark as read", exact=False).count():
                    page.get_by_role("button", name="Mark as read", exact=False).first.click()
                for width in (390, 320):
                    page.set_viewport_size({"width": width, "height": 844})
                    for center in ("profile", "attendance", "results", "fees", "calendar"):
                        visit(
                            f"/portals/parent/students/{child.pk}/{center}/",
                            f"guardian-{center}-{width}",
                        )
                        assert page.evaluate(
                            "document.documentElement.scrollWidth <= innerWidth"
                        ), (width, center)
                    toggle = page.get_by_role("button", name="Open navigation", exact=True)
                    toggle.focus()
                    page.keyboard.press("Enter")
                    assert toggle.get_attribute("aria-expanded") == "true"
                    page.keyboard.press("Escape")
                    assert toggle.get_attribute("aria-expanded") == "false"
                    assert toggle.evaluate("el => document.activeElement === el")
                page.set_viewport_size({"width": 1440, "height": 1100})
                # Revalidate links on an already authenticated browser session.
                db_read(
                    lambda: GuardianStudent.objects.filter(
                        guardian__user__username="demo.parent", student=child
                    ).delete()
                )
                assert (
                    context.request.get(
                        f"{base}/portals/parent/students/{child.pk}/results/"
                    ).status
                    == 404
                )
                assert (
                    context.request.get(
                        f"{base}/examinations/reports/{report.pk}/?format=pdf"
                    ).status
                    == 404
                )
                logout()
                login("demo.teacher")
                visit("/portals/teacher/", "teacher-overview")
                visit("/portals/teacher/classes/", "teacher-classes")
                page.locator(f'a[href="/portals/teacher/classes/{assignment.pk}/"]').click()
                page.get_by_role("link", name="Open attendance register", exact=True).click()
                assert page.get_by_role("heading", name="Class attendance register").is_visible()
                page.get_by_role("button", name="Mark all present", exact=False).click()
                page.locator("#id_confirm").check()
                page.get_by_role("button", name="Save draft", exact=True).click()
                assert page.get_by_text("Attendance draft saved.").is_visible()
                visit(f"/examinations/marks/{sheet.pk}/", "teacher-marks")
                page.locator('input[name$="-marks"]').first.fill("77")
                page.get_by_role("button", name="Save draft marks").click()
                assert (
                    db_read(
                        lambda: (
                            MarkSheet.objects.get(pk=sheet.pk)
                            .entries.order_by(
                                "candidate__enrollment__roll_number",
                                "candidate__student__first_name",
                                "pk",
                            )
                            .first()
                            .marks
                        )
                    )
                    == 77
                )
                page.screenshot(path=str(output / "teacher-marks-saved.png"), full_page=True)
                visit("/attendance/staff/", "teacher-personal-attendance")
                visit("/attendance/leave/", "teacher-leave")
                assert context.request.get(base + "/finance/journal/").status == 403
                visit("/portals/settings/", "teacher-settings")
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
        "Portal Chrome QA passed: student attendance/results/report PDF/fees; "
        "guardian child switching, results/fees/inbox and immediate revocation; "
        "teacher classes/register draft/marks draft/staff attendance/leave; "
        "direct access isolation; 390px/320px overflow and keyboard navigation; "
        "no JavaScript errors."
    )
    print(f"Screenshots: {output}")


if __name__ == "__main__":
    main()
