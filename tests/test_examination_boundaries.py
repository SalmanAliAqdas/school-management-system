import io
import json
import tempfile
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from PIL import Image

from academics.models import ClassSubject, Subject, Term
from core.models import SchoolSettings
from examinations.calculations import calculate_candidate
from examinations.models import (
    Assessment,
    CandidateAmendment,
    ExamCohort,
    ExamController,
    ExaminationSettings,
    ExamSchedule,
    ExamSession,
    ExamSubject,
    GradeBand,
    MarkEntry,
    MarkSheet,
    PublishedResult,
    SessionContribution,
)
from examinations.reporting import analytics, current_results
from examinations.selectors import sheets_visible_to
from examinations.services import (
    decide_amendment,
    decide_correction,
    request_amendment,
    request_correction,
    save_marks,
    save_schedule,
    save_setup,
    session_action,
)
from people.models import Enrollment, Guardian, GuardianStudent, Student

from .helpers import BACKEND, PASSWORD, make_user
from .test_examinations import DAY, ExaminationFixture


class ExaminationBoundaryTests(ExaminationFixture, TestCase):
    def add_component(self, *, optional=False, require_pass=False):
        self.assessment.weight = 25
        self.assessment.max_marks = 40
        save_setup(self.admin, self.assessment)
        return save_setup(
            self.admin,
            Assessment(
                exam_subject=self.subject,
                assessment_type=self.kind,
                name="Practical",
                component="practical",
                max_marks=60,
                weight=75,
                optional=optional,
                require_pass=require_pass,
                passing_percentage=50,
            ),
        )

    def second_session(
        self, name, *, kind="assessment", sources=(), term=None, start=DAY, retake=None
    ):
        session = save_setup(
            self.admin,
            ExamSession(
                academic_year=self.data["year"],
                policy=self.policy,
                assessment_type=self.kind,
                name=name,
                starts_on=start,
                ends_on=start + timedelta(days=10),
                eligibility_on=start,
                report_kind=kind,
                term=term,
                retake_of=retake,
            ),
        )
        save_setup(self.admin, ExamController(session=session, user=self.controller))
        cohort = save_setup(self.admin, ExamCohort(session=session, section=self.data["section"]))
        subject = save_setup(
            self.admin, ExamSubject(cohort=cohort, subject=self.data["subject"], weight=100)
        )
        if kind == "assessment":
            assessment = save_setup(
                self.admin,
                Assessment(
                    exam_subject=subject,
                    assessment_type=self.kind,
                    name="Theory",
                    max_marks=100,
                    weight=100,
                ),
            )
        else:
            assessment = None
            for source, weight in sources:
                save_setup(
                    self.admin, SessionContribution(session=session, source=source, weight=weight)
                )
        return session, cohort, assessment

    def transition(self, session, action, actor=None):
        session.refresh_from_db()
        return session_action(
            actor or self.admin,
            session.pk,
            action,
            expected_version=session.version,
            reason="Fictional academic decision",
        )

    def amend(self, *, withheld, actor=None, teacher_remarks=None):
        self.candidate.refresh_from_db()
        self.session.refresh_from_db()
        return request_amendment(
            actor or self.controller,
            self.candidate.pk,
            teacher_remarks=self.candidate.teacher_remarks
            if teacher_remarks is None
            else teacher_remarks,
            principal_remarks=self.candidate.principal_remarks,
            withheld=withheld,
            withholding_reason="Authorized confidential review" if withheld else "",
            expected_version=self.session.version,
            reason="Fictional independent amendment",
        )

    def test_weighted_components_use_decimal_percentages_not_raw_totals(self):
        practical = self.add_component()
        self.open()
        self.mark("20")
        sheet = MarkSheet.objects.get(assessment=practical)
        save_marks(
            self.teacher,
            sheet.pk,
            {str(self.candidate.pk): {"status": "assessed", "marks": "60", "remarks": ""}},
            expected_version=0,
        )
        result = calculate_candidate(self.candidate)
        self.assertEqual(result["percentage"], "87.50")
        self.assertEqual(Decimal(result["obtained"]), Decimal(80))
        self.assertEqual(Decimal(result["maximum"]), Decimal(100))

    def test_optional_pending_exclusion_is_explicit(self):
        self.add_component(optional=True)
        self.open()
        self.mark("20")
        result = calculate_candidate(self.candidate)
        self.assertEqual(result["percentage"], "50.00")
        self.assertTrue(
            result["subjects"][0]["components"][0].get("excluded")
            or result["subjects"][0]["components"][1].get("excluded")
        )

    def test_required_optional_policy_keeps_pending_incomplete(self):
        self.add_component(optional=True)
        self.policy.optional_rule = "required"
        save_setup(self.admin, self.policy)
        self.open()
        self.mark("20")
        self.assertEqual(calculate_candidate(self.candidate)["outcome"], "incomplete")

    def test_required_component_failure_is_not_masked_by_total(self):
        practical = self.add_component(require_pass=True)
        self.open()
        self.mark("40")
        save_marks(
            self.teacher,
            MarkSheet.objects.get(assessment=practical).pk,
            {str(self.candidate.pk): {"status": "assessed", "marks": "29", "remarks": ""}},
            expected_version=0,
        )
        result = calculate_candidate(self.candidate)
        self.assertGreater(Decimal(result["percentage"]), Decimal(50))
        self.assertEqual(result["outcome"], "fail")

    def test_grade_uses_unrounded_value_even_when_display_rounds_up(self):
        self.open()
        self.mark("49.999")
        result = calculate_candidate(self.candidate)
        self.assertEqual(result["percentage"], "50.00")
        self.assertEqual(result["grade"], "F")
        self.assertEqual(result["outcome"], "fail")

    def test_unrelated_subject_marks_are_invisible_to_teacher(self):
        other = Subject.objects.create(code="EXAM-ENG", name="English")
        ClassSubject.objects.create(
            academic_year=self.data["year"],
            school_class=self.data["section"].school_class,
            subject=other,
        )
        self.subject.weight = 50
        save_setup(self.admin, self.subject)
        subject = save_setup(self.admin, ExamSubject(cohort=self.cohort, subject=other, weight=50))
        assessment = save_setup(
            self.admin,
            Assessment(
                exam_subject=subject,
                assessment_type=self.kind,
                name="English assessment",
                max_marks=100,
                weight=100,
            ),
        )
        self.open()
        sheet = MarkSheet.objects.get(assessment=assessment)
        self.assertFalse(sheets_visible_to(self.teacher).filter(pk=sheet.pk).exists())
        with self.assertRaises(PermissionDenied):
            save_marks(self.teacher, sheet.pk, {}, expected_version=0)

    def test_teacher_analytics_exposes_only_assigned_subject_metrics(self):
        self.publish()
        data = analytics(self.teacher, self.session)
        self.assertFalse(data["oversight"])
        self.assertEqual(len(data["subjects"]), 1)
        self.assertEqual(data["support"], [])
        self.assertEqual(data["grades"], [])

    def test_published_candidate_changes_need_independent_amendment(self):
        old = self.publish()
        request = self.amend(withheld=True)
        with self.assertRaises(ValidationError):
            decide_amendment(self.controller, request.pk, approve=True, reason="Own request")
        decide_amendment(
            self.principal, request.pk, approve=True, reason="Independent visibility review"
        )
        self.candidate.refresh_from_db()
        self.assertTrue(self.candidate.withheld)
        self.assertEqual(self.candidate.results.count(), 2)
        self.client.force_login(self.data["parent"], backend=BACKEND)
        self.assertEqual(
            self.client.get(f"/examinations/reports/{old.pk}/?format=pdf").status_code, 404
        )

    def test_withheld_release_creates_a_new_version_without_destroying_history(self):
        self.publish()
        request = self.amend(withheld=True)
        decide_amendment(self.principal, request.pk, approve=True, reason="Review pending")
        request = self.amend(withheld=False)
        decide_amendment(self.principal, request.pk, approve=True, reason="Review complete")
        versions = list(
            self.candidate.results.order_by("publication__version").values_list(
                "data__outcome", flat=True
            )
        )
        self.assertEqual(versions, ["pass", "withheld", "pass"])

    def test_amendment_rejection_preserves_current_report(self):
        self.publish()
        request = self.amend(withheld=False, teacher_remarks="Revised overall narrative")
        decide_amendment(
            self.principal, request.pk, approve=False, reason="Original narrative confirmed"
        )
        self.assertEqual(self.candidate.results.count(), 1)
        request.refresh_from_db()
        with self.assertRaises(IntegrityError), transaction.atomic():
            CandidateAmendment.objects.filter(pk=request.pk).update(reason="Rewrite history")

    def test_correction_withholding_blocks_prior_versions_and_csv_marks(self):
        old = self.publish()
        entry = MarkEntry.objects.get(candidate=self.candidate)
        request = request_correction(
            self.controller,
            entry.pk,
            status="withheld",
            marks=None,
            remarks="Review in progress",
            reason="Restricted script review",
        )
        decide_correction(
            self.principal, request.pk, approve=True, reason="Independent review accepted"
        )
        self.client.force_login(self.data["student_user"], backend=BACKEND)
        self.assertEqual(self.client.get(f"/examinations/reports/{old.pk}/").status_code, 404)
        response = self.client.get("/examinations/results/?format=csv")
        self.assertNotIn(b"80.00", response.content)
        self.assertIn(b"withheld", response.content)

    def test_duplicate_pending_requests_are_rejected(self):
        self.publish()
        self.amend(withheld=True)
        with self.assertRaises(ValidationError):
            self.amend(withheld=True)

    def test_term_and_annual_sources_are_explicit_and_snapshotted(self):
        original = self.publish("80")
        term = Term.objects.create(
            academic_year=self.data["year"],
            name="Fictional autumn",
            starts_on=self.data["year"].starts_on,
            ends_on=self.data["year"].ends_on,
        )
        # An assessment without a term is valid for annual consolidation.
        annual, _, _ = self.second_session(
            "Annual report", kind="annual", sources=[(self.session, 100)]
        )
        for action, actor in (
            ("open", self.admin),
            ("close", self.admin),
            ("review", self.controller),
            ("approve", self.principal),
            ("publish", self.admin),
        ):
            self.transition(annual, action, actor)
        report = PublishedResult.objects.get(candidate__session=annual)
        self.assertEqual(report.data["percentage"], "80.00")
        self.assertEqual(
            report.data["subjects"][0]["components"][0]["publication"], str(original.publication_id)
        )
        with self.assertRaisesMessage(ValidationError, "from that term"):
            self.second_session(
                "Invalid term", kind="term", term=term, sources=[(self.session, 100)]
            )

    def test_invalid_source_weights_do_not_normalize(self):
        self.publish()
        report, _, _ = self.second_session(
            "Incomplete annual weights", kind="annual", sources=[(self.session, 90)]
        )
        with self.assertRaisesMessage(ValidationError, "exactly 100"):
            self.transition(report, "open")

    def test_retakes_keep_original_results_and_limit_original_candidates(self):
        original = self.publish()
        start = DAY + timedelta(days=11)
        session, _, assessment = self.second_session(
            "Supplementary", start=start, retake=self.session
        )
        self.transition(session, "open")
        self.assertEqual(
            list(session.candidates.values_list("student_id", flat=True)), [self.data["own"].pk]
        )
        self.assertEqual(PublishedResult.objects.get(pk=original.pk).data["percentage"], "80.00")
        self.assertEqual(MarkSheet.objects.get(assessment=assessment).state, "draft")

    def test_rankings_ties_and_private_personal_position(self):
        second = Student.objects.create(
            first_name="Tie", last_name="Example", admission_number="EXAM-TIE"
        )
        Enrollment.objects.create(
            student=second,
            academic_year=self.data["year"],
            section=self.data["section"],
            started_on=self.data["year"].starts_on,
        )
        save_setup(self.admin, ExaminationSettings(ranking_enabled=True))
        self.open()
        rows = {
            str(c.pk): {"status": "assessed", "marks": "80", "remarks": ""}
            for c in self.session.candidates.all()
        }
        self.sheet = save_marks(self.teacher, self.sheet.pk, rows, expected_version=0, submit=True)
        self.approve_sheet()
        self.action("close")
        self.action("review", self.controller)
        self.action("approve", self.principal)
        self.action("publish")
        self.assertEqual(
            [r.data["rank"] for r in self.session.publications.first().results.all()], [1, 1]
        )
        self.client.force_login(self.data["parent"], backend=BACKEND)
        response = self.client.get("/examinations/results/")
        self.assertNotContains(response, "Tie Example")

    def test_guardian_many_children_and_multiple_guardians_remain_scoped(self):
        self.publish()
        second_parent = make_user("secondexamguardian", "Parent or Guardian")
        guardian = Guardian.objects.create(
            user=second_parent, first_name="Second", last_name="Guardian"
        )
        GuardianStudent.objects.create(
            guardian=guardian, student=self.data["own"], relationship="Guardian"
        )
        self.assertEqual(current_results(second_parent).count(), 1)
        GuardianStudent.objects.create(
            guardian=self.data["guardian"], student=self.data["other"], relationship="Guardian"
        )
        self.assertEqual(current_results(self.data["parent"]).count(), 1)

    def test_empty_analytics_and_invalid_filters_have_meaningful_responses(self):
        self.open()
        self.assertIsNone(analytics(self.admin, self.session)["average"])
        response = self.client.get("/examinations/results/?session=not-a-uuid")
        self.assertEqual(response.status_code, 200)
        self.assertIn("session", response.context["form"].errors)
        self.assertEqual(
            self.client.get("/examinations/schedules/?session=not-a-uuid").status_code, 404
        )

    def test_direct_database_enrollment_changes_cannot_break_exam_history(self):
        self.open()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Enrollment.objects.filter(pk=self.candidate.enrollment_id).update(
                ended_on=DAY - timedelta(days=1), is_active=False
            )

    def test_schedule_identity_and_duty_dates_are_database_protected(self):
        slot = save_schedule(
            self.admin,
            assessment_id=self.assessment.pk,
            starts_at=self.at(),
            ends_at=self.at(hour=10),
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            ExamSchedule.objects.filter(pk=slot.pk).update(section=self.data["other_section"])
        self.open()
        self.mark()
        with self.assertRaises(ValidationError):
            save_schedule(
                self.admin,
                assessment_id=self.assessment.pk,
                starts_at=self.at(hour=11),
                ends_at=self.at(hour=12),
            )

    def test_policy_band_overlap_is_rejected_by_database(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            GradeBand.objects.create(policy=self.policy, lower=40, upper=60, label="Overlap")

    def test_incomplete_reports_are_excluded_from_average(self):
        self.publish(None, "pending")
        data = analytics(self.admin, self.session)
        self.assertEqual(data["incomplete"], 1)
        self.assertIsNone(data["average"])
        self.assertIsNone(data["pass_percentage"])

    def test_closed_and_archived_marks_remain_protected(self):
        self.publish()
        self.action("archive")
        entry = MarkEntry.objects.get(candidate=self.candidate)
        with self.assertRaisesMessage(ValidationError, "before archival"):
            request_correction(
                self.controller,
                entry.pk,
                status="assessed",
                marks="90",
                remarks="",
                reason="Late request",
            )

    def test_read_only_get_never_publishes_or_marks_notice_read(self):
        self.open()
        state = self.session.state
        self.client.get(f"/examinations/sessions/{self.session.pk}/actions/publish/")
        self.session.refresh_from_db()
        self.assertEqual(self.session.state, state)

    def test_query_count_for_teacher_sheet_scope_is_bounded(self):
        self.open()
        # Warm group permission caches; scope should use correlated SQL, not a query per session.
        list(sheets_visible_to(self.teacher))
        with CaptureQueriesContext(connection) as queries:
            list(sheets_visible_to(self.teacher))
        self.assertLessEqual(len(queries), 2)

    def test_report_identity_and_images_survive_source_replacement(self):
        with (
            tempfile.TemporaryDirectory() as media,
            override_settings(
                STORAGES={
                    "default": {
                        "BACKEND": "django.core.files.storage.FileSystemStorage",
                        "OPTIONS": {"location": media},
                    },
                    "staticfiles": {
                        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
                    },
                }
            ),
        ):
            image = io.BytesIO()
            Image.new("RGB", (10, 10), "green").save(image, "PNG")
            school = SchoolSettings.objects.get(pk=1)
            school.name = "Fictional Snapshot School"
            school.logo = SimpleUploadedFile(
                "fictional.png", image.getvalue(), content_type="image/png"
            )
            school.save()
            result = self.publish()
            self.client.force_login(self.data["parent"], backend=BACKEND)
            original_pdf = self.client.get(f"/examinations/reports/{result.pk}/?format=pdf").content
            original = json.dumps(result.data, sort_keys=True)
            path = Path(school.logo.path)
            school.name = "Changed current identity"
            school.logo = ""
            school.save()
            path.unlink()
            result.refresh_from_db()
            self.assertEqual(json.dumps(result.data, sort_keys=True), original)
            self.client.force_login(self.data["parent"], backend=BACKEND)
            self.assertEqual(
                self.client.get(f"/examinations/reports/{result.pk}/images/logo/").status_code, 200
            )
            self.assertTrue(
                self.client.get(
                    f"/examinations/reports/{result.pk}/?format=pdf"
                ).content.startswith(b"%PDF")
            )

            self.assertEqual(
                self.client.get(f"/examinations/reports/{result.pk}/?format=pdf").content,
                original_pdf,
            )

    def test_nonprincipal_approval_can_be_configured_explicitly(self):
        self.policy.principal_approval = False
        save_setup(self.admin, self.policy)
        self.open()
        self.mark()
        self.approve_sheet()
        self.action("close")
        self.action("review", self.controller)
        self.action("approve", self.controller)
        self.assertEqual(self.session.approved_by, self.controller)

    def test_publication_does_not_issue_a_query_for_each_student(self):
        for index in range(20):
            student = Student.objects.create(
                first_name=f"Query{index}", last_name="Fictional", admission_number=f"EX-Q-{index}"
            )
            Enrollment.objects.create(
                student=student,
                academic_year=self.data["year"],
                section=self.data["section"],
                started_on=self.data["year"].starts_on,
            )
        self.open()
        rows = {
            str(c.pk): {"status": "assessed", "marks": "80", "remarks": ""}
            for c in self.session.candidates.all()
        }
        self.sheet = save_marks(self.teacher, self.sheet.pk, rows, expected_version=0, submit=True)
        self.approve_sheet()
        self.action("close")
        self.action("review", self.controller)
        self.action("approve", self.principal)
        with CaptureQueriesContext(connection) as queries:
            self.action("publish")
        self.assertLess(len(queries), 65)
        self.assertEqual(PublishedResult.objects.count(), 21)

    def test_school_issue_date_and_timezone_are_captured(self):
        result = self.publish()
        self.assertEqual(result.data["school"]["timezone"], "Asia/Karachi")
        self.assertTrue(result.data["issued_at"].endswith("+05:00"))

    def test_promotion_form_shows_evidence_without_changing_enrollment(self):
        self.publish()
        response = self.client.get(f"/students/{self.data['own'].pk}/enrollment/")
        self.assertContains(response, "Latest published academic recommendation")
        self.assertContains(response, "Eligible for school review")
        self.assertTrue(Enrollment.objects.get(pk=self.candidate.enrollment_id).is_active)

    def test_controllers_can_assign_reviewers_only_to_controlled_sessions(self):
        save_setup(self.controller, ExamController(session=self.session, user=self.outsider))
        self.assertTrue(self.session.controllers.filter(pk=self.outsider.pk).exists())
        unrelated, _, _ = self.second_session("Unrelated controller scope")
        unrelated.controller_links.filter(user=self.controller).delete()
        with self.assertRaises(PermissionDenied):
            save_setup(self.controller, ExamController(session=unrelated, user=self.controller))
        self.client.force_login(self.controller, backend=BACKEND)
        self.assertEqual(self.client.get("/examinations/setup/controllers/new/").status_code, 200)

    def test_examination_demo_is_repeatable_without_overwriting_records(self):
        with override_settings(DEBUG=True, ALLOW_DEMO_DATA=True):
            from unittest.mock import patch

            with patch.dict("os.environ", {"DEMO_PASSWORD": PASSWORD}):
                call_command("seed_demo", stdout=io.StringIO())
                before = {
                    r.pk: json.dumps(r.data, sort_keys=True) for r in PublishedResult.objects.all()
                }
                count = ExamSession.objects.count()
                call_command("seed_demo", stdout=io.StringIO())
        self.assertEqual(ExamSession.objects.count(), count)
        self.assertEqual(
            {r.pk: json.dumps(r.data, sort_keys=True) for r in PublishedResult.objects.all()},
            before,
        )
