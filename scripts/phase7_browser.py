"""Exercise Phase 7 in installed Chrome against an owned disposable PostgreSQL database."""

import os
import secrets
import sys
import threading
import uuid
from datetime import time, timedelta
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

    from academics.models import TeachingAssignment
    from attendance.calendar import school_now
    from core.models import SchoolSettings
    from scheduling.models import Period, Room
    from tests.helpers import make_school_data, make_user

    original = connection.settings_dict["NAME"]
    settings.DATABASES["default"].setdefault("TEST", {})["NAME"] = (
        "test_phase7_browser_" + uuid.uuid4().hex[:12]
    )
    old = setup_databases(verbosity=0, interactive=False)
    assert connection.settings_dict["NAME"] != original
    server = thread = None
    output = ROOT / ".local/previews/phase7"
    output.mkdir(parents=True, exist_ok=True)

    class Quiet(WSGIRequestHandler):
        def log_message(self, *args):
            pass

    try:
        d = make_school_data()
        principal = make_user("principal", "Principal")
        SchoolSettings.objects.create(name="Fictional Learning School")
        d["teacher"].joined_on = d["year"].starts_on
        d["teacher"].save()
        password = secrets.token_urlsafe(24) + "-Fictional!"
        for user in [d["admin"], d["student_user"], d["parent"], d["teacher_user"], principal]:
            user.set_password(password)
            user.save()
        today = school_now().date()
        now = school_now()
        period = Period.objects.create(
            academic_year=d["year"],
            name="Morning learning",
            weekday=today.weekday(),
            starts_at=time(8),
            ends_at=time(8, 40),
        )
        overlap = Period.objects.create(
            academic_year=d["year"],
            name="Conflicting period",
            weekday=today.weekday(),
            starts_at=time(8, 20),
            ends_at=time(9),
        )
        room = Room.objects.create(name="Learning Studio")
        teaching = TeachingAssignment.objects.get(teacher=d["teacher"])
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
                context = browser.new_context(
                    viewport={"width": 1440, "height": 1050}, reduced_motion="reduce"
                )
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "console",
                    lambda message: (
                        errors.append(message.text) if message.type == "error" else None
                    ),
                )

                def visit(path):
                    response = page.goto(base + path)
                    assert response.status == 200, (path, response.status)

                def login(username):
                    visit("/accounts/login/")
                    page.get_by_label("Username", exact=False).fill(username)
                    page.get_by_label("Password", exact=False).fill(password)
                    page.get_by_role("button", name="Sign in to workspace").click()
                    page.wait_for_url("**/dashboard/**")

                def logout():
                    page.get_by_role("button", name="Sign out").click()
                    page.wait_for_url("**/accounts/login/")

                def shot(name):
                    page.screenshot(path=str(output / (name + ".png")), full_page=True)

                def save():
                    page.get_by_role("button", name="Save", exact=True).click()

                login("administrator")
                visit("/scheduling/new/")
                page.locator("#id_title").fill("Autumn learning week")
                page.locator("#id_academic_year").select_option(str(d["year"].pk))
                page.get_by_label("Starts on").fill(today.isoformat())
                page.get_by_label("Ends on").fill((today + timedelta(days=6)).isoformat())
                save()
                page.wait_for_url("**/scheduling/*/")
                table_path = page.url.replace(base, "")
                page.get_by_role("link", name="Add lesson", exact=True).click()
                page.locator("#id_period").select_option(str(period.pk))
                page.locator("#id_assignment").select_option(str(teaching.pk))
                page.locator("#id_room").select_option(str(room.pk))
                save()
                page.wait_for_url(base + table_path)
                page.get_by_role("link", name="Add lesson", exact=True).click()
                page.locator("#id_period").select_option(str(overlap.pk))
                page.locator("#id_assignment").select_option(str(teaching.pk))
                page.locator("#id_room").select_option(str(room.pk))
                save()
                assert (
                    page.get_by_text(
                        "Teacher conflict: another class occupies this time.", exact=True
                    ).count()
                    == 1
                )
                shot("conflict-rejected")
                visit(table_path)
                page.get_by_role("button", name="Validate & publish").click()
                assert page.get_by_text("Published", exact=False).count() > 0
                shot("weekly-timetable")
                logout()
                login("educator")
                visit("/scheduling/")
                assert page.get_by_text("Mathematics", exact=True).count() > 0
                visit("/learning/new/")
                page.locator("#id_teaching").select_option(str(teaching.pk))
                page.locator("#id_title").fill("A fraction of our day")
                page.locator("#id_description").fill(
                    "Explain a fraction using an everyday example."
                )
                page.get_by_label("Publish at").fill(
                    (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
                )
                page.get_by_label("Due at").fill(
                    (now + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
                )
                page.locator("#id_maximum").fill("100")
                save()
                page.wait_for_url("**/learning/*/")
                work_path = page.url.replace(base, "")
                page.get_by_role("button", name="Publish assignment").click()
                shot("teacher-assignment")
                logout()
                login("learner")
                visit(table_path)
                visit(work_path)
                page.get_by_role("link", name="Open submission").click()
                page.locator("#id_text").fill(
                    "I shared a loaf into four equal pieces. One piece is one quarter."
                )
                page.locator("input[type=file]").set_input_files(
                    {
                        "name": "reasoning.txt",
                        "mimeType": "text/plain",
                        "buffer": b"One quarter is one of four equal parts.",
                    }
                )
                page.get_by_label("Submit final work", exact=False).check()
                save()
                page.wait_for_url(base + work_path)
                assert page.get_by_text("Submitted", exact=True).count() == 1
                shot("student-submission")
                logout()
                login("educator")
                visit(work_path)
                page.get_by_role("link", name="Review work", exact=True).click()
                page.locator("#id_text").fill("Clear reasoning and a useful example.")
                page.locator("#id_outcome").select_option("graded")
                page.locator("#id_marks").fill("88")
                page.get_by_label("Release to student").check()
                page.get_by_label("Also allow linked guardians", exact=False).check()
                save()
                page.wait_for_url(base + work_path)
                visit("/communications/messages/new/?student=" + str(d["own"].pk))
                page.locator("#id_recipient").select_option(str(d["parent"].pk))
                page.locator("#id_subject").fill("A thoughtful start")
                page.locator("#id_body").fill("Your child has explained fractions clearly.")
                page.get_by_role("button", name="Send message", exact=True).click()
                page.wait_for_url("**/communications/messages/*/")
                thread_path = page.url.replace(base, "")
                logout()
                login("guardian")
                visit(table_path)
                visit(work_path)
                assert (
                    page.get_by_text("Clear reasoning and a useful example.", exact=True).count()
                    == 1
                )
                shot("guardian-feedback")
                visit(thread_path)
                page.locator("#id_body").fill("Thank you. We will celebrate the progress together.")
                page.get_by_role("button", name="Send reply").click()
                assert (
                    page.get_by_text(
                        "Thank you. We will celebrate the progress together.", exact=True
                    ).count()
                    == 1
                )
                shot("family-conversation")
                logout()
                login("administrator")
                visit("/communications/publications/new/")
                page.locator("#id_kind").select_option("event")
                page.locator("#id_title").fill("Learning together evening")
                page.locator("#id_body").fill("Join us to share learning progress.")
                page.get_by_label("Publish at").fill(
                    (now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M")
                )
                page.get_by_label("Starts at").fill(
                    (now + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M")
                )
                page.get_by_label("Ends at").fill(
                    (now + timedelta(days=3, hours=1)).strftime("%Y-%m-%dT%H:%M")
                )
                save()
                page.wait_for_url("**/communications/publications/*/")
                event_path = page.url.replace(base, "")
                page.get_by_role("button", name="Submit for approval").click()
                logout()
                login("principal")
                visit(event_path)
                page.get_by_role("button", name="Approve & publish").click()
                logout()
                login("learner")
                visit(event_path)
                assert context.request.get(base + thread_path).status == 404
                visit("/communications/calendar/")
                shot("student-calendar")
                logout()
                login("guardian")
                visit(event_path)
                for width in [768, 390, 320]:
                    page.set_viewport_size({"width": width, "height": 900})
                    for path in [
                        "/scheduling/",
                        table_path,
                        "/learning/",
                        work_path,
                        "/communications/calendar/",
                        "/communications/",
                        thread_path,
                        "/portals/parent/",
                    ]:
                        visit(path)
                        assert page.evaluate(
                            "document.documentElement.scrollWidth <= window.innerWidth"
                        ), (width, path)
                    shot("guardian-mobile-" + str(width))
                page.get_by_role("button", name="Open navigation").focus()
                page.keyboard.press("Enter")
                assert (
                    page.get_by_role("button", name="Open navigation").get_attribute(
                        "aria-expanded"
                    )
                    == "true"
                )
                page.keyboard.press("Escape")
                assert (
                    page.get_by_role("button", name="Open navigation").get_attribute(
                        "aria-expanded"
                    )
                    == "false"
                )
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
    print(
        "Phase 7 Chrome QA passed: draft, conflict rejection, publication, "
        "student/guardian/teacher timetables, homework submission/files/grading, "
        "guardian feedback, event approval, authorized message/reply and unrelated denial; "
        "tablet/390px/320px overflow, keyboard navigation, no console errors."
    )
    print(f"Screenshots: {output}")


if __name__ == "__main__":
    main()
