"""Exercise Phase 4 in a uniquely named disposable PostgreSQL database, using Chrome.

Never serves or resets the application database. Generated fixture credentials remain
in memory, and only this script's isolated test database is removed on completion.
"""

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
    from django.contrib.auth import get_user_model
    from django.contrib.staticfiles.handlers import StaticFilesHandler
    from django.core.management import call_command
    from django.core.wsgi import get_wsgi_application
    from django.db import connection, connections
    from django.test import override_settings
    from django.test.utils import setup_databases, teardown_databases
    from playwright.sync_api import sync_playwright

    from academics.models import AcademicYear, Section, Subject
    from examinations.models import (
        Assessment,
        AssessmentType,
        ExamCohort,
        ExamSubject,
        GradingPolicy,
        MarkEntry,
        MarkSheet,
        PublishedResult,
        ResultCorrection,
    )
    from people.models import Student

    original_name = connection.settings_dict["NAME"]
    settings.DATABASES["default"].setdefault("TEST", {})["NAME"] = (
        f"test_examination_browser_{uuid.uuid4().hex[:12]}"
    )
    old_config = setup_databases(verbosity=0, interactive=False)
    if connection.settings_dict["NAME"] == original_name:
        raise RuntimeError("Browser QA requires an isolated test database.")
    server = thread = None
    output = ROOT / ".local" / "previews" / "examinations"
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
            section = Section.objects.get(school_class__name="Grade 6", name="A")
            subject = Subject.objects.get(code="DEMO-MATH")
            policy = GradingPolicy.objects.get(name="DEMO · Assessment policy v1")
            kind = AssessmentType.objects.get(name="DEMO · Class test")
            controller = get_user_model().objects.get(username="demo.exams")
            child = Student.objects.get(admission_number="DEMO-0001")
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

            def db_read(callback):
                def worker():
                    try:
                        return callback()
                    finally:
                        connections.close_all()

                with ThreadPoolExecutor(max_workers=1) as pool:
                    return pool.submit(worker).result(timeout=10)

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
                    page.wait_for_url("**/dashboard/**")

                def logout():
                    page.get_by_role("button", name="Sign out", exact=True).click()
                    page.wait_for_url("**/accounts/login/")

                def save():
                    page.get_by_role("button", name="Save and continue", exact=True).click()
                    assert page.locator(".field-error,.alert-danger").count() == 0, page.locator(
                        "#main-content"
                    ).inner_text()

                def action(session_id, name):
                    assert (
                        page.goto(
                            f"{base}/examinations/sessions/{session_id}/actions/{name}/"
                        ).status
                        == 200
                    )
                    page.locator("#id_reason").fill(
                        "Verified through the fictional browser acceptance workflow."
                    )
                    page.get_by_label("I confirm this action", exact=False).check()
                    save()
                    page.wait_for_url(f"**/examinations/sessions/{session_id}/")

                def screenshot(route, name, *, mobile=False):
                    page.set_viewport_size(
                        {"width": 390, "height": 844} if mobile else {"width": 1440, "height": 1100}
                    )
                    assert page.goto(base + route).status == 200
                    page.screenshot(
                        path=str(output / f"{name}-{'mobile' if mobile else 'desktop'}.png"),
                        full_page=True,
                    )
                    assert page.evaluate(
                        "document.documentElement.scrollWidth <= innerWidth + 2"
                    ), f"Horizontal overflow: {route}"

                login("demo.admin")
                assert page.goto(f"{base}/examinations/setup/sessions/new/").status == 200
                page.locator("#id_academic_year").select_option(str(year.pk))
                page.locator("#id_assessment_type").select_option(str(kind.pk))
                page.locator("#id_policy").select_option(str(policy.pk))
                page.locator("#id_name").fill("Browser acceptance assessment")
                for label, value in (
                    ("Starts on", "2026-10-05"),
                    ("Ends on", "2026-10-09"),
                    ("Eligibility on", "2026-10-05"),
                ):
                    page.locator(
                        "#id_"
                        + {
                            "Starts on": "starts_on",
                            "Ends on": "ends_on",
                            "Eligibility on": "eligibility_on",
                        }[label]
                    ).fill(value)
                save()
                page.wait_for_url("**/examinations/sessions/*/")
                session_id = page.url.rstrip("/").split("/")[-1]
                assert (
                    page.goto(
                        f"{base}/examinations/setup/controllers/new/?session={session_id}"
                    ).status
                    == 200
                )
                page.locator("#id_user").select_option(str(controller.pk))
                save()
                page.goto(f"{base}/examinations/setup/cohorts/new/?session={session_id}")
                page.locator("#id_section").select_option(str(section.pk))
                save()
                cohort_id = db_read(lambda: ExamCohort.objects.get(session_id=session_id).pk)
                page.goto(f"{base}/examinations/setup/subjects/new/?cohort={cohort_id}")
                page.locator("#id_subject").select_option(str(subject.pk))
                page.locator("#id_weight").fill("100")
                page.locator("#id_passing_percentage").fill("50")
                save()
                subject_id = db_read(lambda: ExamSubject.objects.get(cohort_id=cohort_id).pk)
                page.goto(f"{base}/examinations/setup/assessments/new/?exam_subject={subject_id}")
                page.locator("#id_assessment_type").select_option(str(kind.pk))
                page.locator("#id_name").fill("Written assessment")
                page.locator("#id_max_marks").fill("100")
                page.locator("#id_weight").fill("100")
                save()
                assessment_id = db_read(
                    lambda: Assessment.objects.get(exam_subject_id=subject_id).pk
                )
                page.goto(f"{base}/examinations/sessions/{session_id}/schedule/")
                page.locator("#id_assessment").select_option(str(assessment_id))
                page.locator("#id_starts_at").fill("2026-10-07T14:00")
                page.locator("#id_ends_at").fill("2026-10-07T15:00")
                save()
                action(session_id, "open")
                sheet_id = db_read(lambda: MarkSheet.objects.get(assessment_id=assessment_id).pk)
                screenshot("/examinations/", "dashboard")
                screenshot("/examinations/setup/policies/", "grading-policies")
                screenshot(f"/examinations/sessions/{session_id}/", "session")
                logout()

                login("demo.teacher")
                page.goto(f"{base}/examinations/marks/{sheet_id}/")
                rows = page.locator("[data-exam-row]")
                assert rows.count() == 2
                for index in range(rows.count()):
                    row = rows.nth(index)
                    row.locator('select[name$="-status"]').select_option("assessed")
                    row.locator('input[name$="-marks"]').fill("88" if index == 0 else "72")
                    row.locator('input[name$="-remarks"]').fill(
                        "Good progress in the fictional assessment."
                    )
                page.get_by_role("button", name="Save draft marks", exact=True).click()
                assert db_read(lambda: MarkSheet.objects.get(pk=sheet_id).state) == "draft"
                screenshot(f"/examinations/marks/{sheet_id}/", "teacher-marks")
                screenshot(f"/examinations/marks/{sheet_id}/", "teacher-marks", mobile=True)
                page.set_viewport_size({"width": 1440, "height": 1100})
                page.get_by_role("button", name="Submit marks for review", exact=True).click()
                assert db_read(lambda: MarkSheet.objects.get(pk=sheet_id).state) == "submitted"
                logout()
                login("demo.exams")
                page.goto(f"{base}/examinations/marks/{sheet_id}/review/")
                page.locator("#id_decision").select_option("approve")
                page.locator("#id_reason").fill("Independently reviewed against fictional scripts.")
                page.get_by_label("I confirm this action", exact=False).check()
                screenshot(f"/examinations/marks/{sheet_id}/review/", "controller-review")
                # Screenshot reloads the form; enter the review again.
                page.locator("#id_decision").select_option("approve")
                page.locator("#id_reason").fill("Independent fictional script review.")
                page.get_by_label("I confirm this action", exact=False).check()
                save()
                logout()
                login("demo.admin")
                action(session_id, "close")
                logout()
                login("demo.exams")
                action(session_id, "review")
                logout()
                login("demo.principal")
                action(session_id, "approve")
                logout()
                login("demo.admin")
                action(session_id, "publish")
                report_id = db_read(
                    lambda: (
                        PublishedResult.objects.get(
                            candidate__session_id=session_id, candidate__student=child
                        ).pk
                    )
                )
                other_report_id = db_read(
                    lambda: (
                        PublishedResult.objects.filter(candidate__session_id=session_id)
                        .exclude(candidate__student=child)
                        .get()
                        .pk
                    )
                )
                for route, name in [
                    (f"/examinations/reports/{report_id}/", "report-card"),
                    (f"/examinations/sessions/{session_id}/analytics/", "analytics"),
                    (f"/examinations/schedules/?session={session_id}", "date-sheet"),
                    ("/examinations/results/", "published-results"),
                    ("/examinations/corrections/", "corrections"),
                ]:
                    screenshot(route, name)
                    screenshot(route, name, mobile=True)
                page.set_viewport_size({"width": 1440, "height": 1100})
                logout()
                login("demo.teacher")
                entry_id = db_read(
                    lambda: MarkEntry.objects.get(sheet_id=sheet_id, candidate__student=child).pk
                )
                page.goto(f"{base}/examinations/corrections/marks/{entry_id}/")
                page.locator("#id_marks").fill("90")
                page.locator("#id_reason").fill(
                    "Verified two additional points in the fictional script."
                )
                page.get_by_label("Request independent review", exact=False).check()
                save()
                logout()
                login("demo.exams")
                correction_id = db_read(
                    lambda: ResultCorrection.objects.get(entry_id=entry_id, state="pending").pk
                )
                page.goto(f"{base}/examinations/corrections/{correction_id}/review/")
                page.locator("#id_approve").select_option("yes")
                page.locator("#id_reason").fill(
                    "Independent rechecking confirms two additional points."
                )
                page.get_by_label("I reviewed the original", exact=False).check()
                save()
                logout()
                login("demo.student")
                new_report_id = db_read(
                    lambda: (
                        PublishedResult.objects.filter(
                            candidate__session_id=session_id, candidate__student=child
                        )
                        .order_by("-publication__version")
                        .first()
                        .pk
                    )
                )
                assert page.goto(f"{base}/examinations/reports/{new_report_id}/").status == 200
                assert "90.00" in page.locator(".exam-report").inner_text()
                assert (
                    context.request.get(
                        f"{base}/examinations/reports/{other_report_id}/?format=pdf"
                    ).status
                    == 404
                )
                with page.expect_download() as download:
                    page.get_by_role("link", name="Download PDF", exact=True).click()
                download_path = Path(download.value.path())
                assert download_path.read_bytes().startswith(b"%PDF-")
                assert context.request.get(f"{base}/examinations/marks/{sheet_id}/").status == 404
                screenshot("/examinations/", "student-portal", mobile=True)
                logout()
                login("demo.parent")
                assert page.goto(f"{base}/examinations/reports/{new_report_id}/").status == 200
                assert (
                    context.request.get(f"{base}/examinations/reports/{other_report_id}/").status
                    == 404
                )
                response = context.request.get(
                    f"{base}/examinations/results/?session={session_id}&format=csv"
                )
                assert response.status == 200 and b"DEMO-0004" not in response.body()
                screenshot("/examinations/", "guardian-portal")
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
        "Examination browser QA passed: administrator setup/scheduling, teacher draft/submission, "
        "controller review, principal approval, publication, correction/republication, "
        "student/guardian isolation, report cards/PDF/CSV and desktop/mobile screens."
    )
    print(f"Screenshots: {output}")


if __name__ == "__main__":
    main()
