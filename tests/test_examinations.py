from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase

from academics.models import ClassSubject, TeachingAssignment
from examinations.calculations import calculate_candidate, grade_for, validate_policy
from examinations.models import (
    Assessment,
    AssessmentType,
    ExamCandidate,
    ExamCohort,
    ExamController,
    ExamRoom,
    ExamSession,
    ExamSubject,
    GradeBand,
    GradingPolicy,
    MarkEntry,
    MarkSheet,
    PublishedResult,
)
from examinations.selectors import (
    notifications_visible_to,
    sessions_visible_to,
    subjects_visible_to,
)
from examinations.services import (
    decide_correction,
    override_recommendation,
    request_correction,
    review_sheet,
    save_marks,
    save_schedule,
    save_setup,
    session_action,
    update_candidate,
)
from people.models import Enrollment, GuardianStudent
from people.services import transition_student

from .helpers import BACKEND, make_school_data, make_user

DAY = date(2026, 10, 5)


class ExaminationFixture:
    @classmethod
    def setUpTestData(cls):
        cls.data = make_school_data()
        cls.admin = cls.data["admin"]
        cls.teacher = cls.data["teacher_user"]
        cls.principal = make_user("examprincipal", "Principal")
        cls.controller = make_user("examcontroller", "Examination Controller")
        cls.outsider = make_user("othercontroller", "Examination Controller")
        ClassSubject.objects.create(
            academic_year=cls.data["year"],
            school_class=cls.data["section"].school_class,
            subject=cls.data["subject"],
        )
        cls.kind = save_setup(cls.admin, AssessmentType(name="Midterm"))
        cls.policy = save_setup(
            cls.admin, GradingPolicy(academic_year=cls.data["year"], name="Fictional scale")
        )
        for lower, upper, label in ((0, 50, "F"), (50, 70, "C"), (70, 90, "B"), (90, 100, "A")):
            save_setup(
                cls.admin, GradeBand(policy=cls.policy, lower=lower, upper=upper, label=label)
            )
        cls.session = save_setup(
            cls.admin,
            ExamSession(
                academic_year=cls.data["year"],
                policy=cls.policy,
                assessment_type=cls.kind,
                name="Fictional midterm",
                starts_on=DAY,
                ends_on=DAY + timedelta(days=10),
                eligibility_on=DAY,
            ),
        )
        save_setup(cls.admin, ExamController(session=cls.session, user=cls.controller))
        cls.cohort = save_setup(
            cls.admin, ExamCohort(session=cls.session, section=cls.data["section"])
        )
        cls.subject = save_setup(
            cls.admin, ExamSubject(cohort=cls.cohort, subject=cls.data["subject"], weight=100)
        )
        cls.assessment = save_setup(
            cls.admin,
            Assessment(
                exam_subject=cls.subject,
                assessment_type=cls.kind,
                name="Theory",
                max_marks=100,
                weight=100,
            ),
        )

    def setUp(self):
        self.client.force_login(self.admin, backend=BACKEND)

    def action(self, action, actor=None):
        self.session.refresh_from_db()
        self.session = session_action(
            actor or self.admin,
            self.session.pk,
            action,
            expected_version=self.session.version,
            reason="Fictional authorized school decision",
        )
        return self.session

    def open(self):
        self.action("open")
        self.sheet = MarkSheet.objects.get(assessment=self.assessment)
        self.candidate = ExamCandidate.objects.get(cohort=self.cohort, student=self.data["own"])

    def mark(self, value="80", status="assessed", *, submit=True, actor=None, remarks=""):
        self.sheet.refresh_from_db()
        self.sheet = save_marks(
            actor or self.teacher,
            self.sheet.pk,
            {str(self.candidate.pk): {"status": status, "marks": value, "remarks": remarks}},
            expected_version=self.sheet.version,
            submit=submit,
        )
        return self.sheet

    def approve_sheet(self):
        self.sheet.refresh_from_db()
        self.sheet = review_sheet(
            self.controller,
            self.sheet.pk,
            "approve",
            expected_version=self.sheet.version,
            reason="Checked against the fictional script",
        )

    def publish(self, value="80", status="assessed", remarks=""):
        self.open()
        self.mark(value, status, remarks=remarks)
        self.approve_sheet()
        self.action("close")
        self.action("review", self.controller)
        self.action("approve", self.principal)
        self.action("publish")
        return PublishedResult.objects.get(candidate=self.candidate)

    def at(self, day=DAY, hour=9):
        return datetime(day.year, day.month, day.day, hour, tzinfo=ZoneInfo("Asia/Karachi"))


class ExaminationTests(ExaminationFixture, TestCase):
    def test_configuration_and_dated_roster_reuse_enrollment(self):
        self.open()
        self.assertEqual(self.candidate.enrollment.student, self.data["own"])
        self.assertEqual(ExamCandidate.objects.count(), 1)
        self.assertEqual(MarkSheet.objects.count(), 1)

    def test_weights_must_total_exactly_one_hundred(self):
        self.assessment.weight = 90
        save_setup(self.admin, self.assessment)
        with self.assertRaisesMessage(ValidationError, "exactly 100"):
            self.open()
        self.assertFalse(ExamCandidate.objects.exists())

    def test_policy_band_gaps_and_overlaps_are_rejected(self):
        GradeBand.objects.filter(policy=self.policy, lower=50).update(lower=51)
        with self.assertRaisesMessage(ValidationError, "gaps or overlaps"):
            validate_policy(self.policy)

    def test_grade_boundaries_are_decimal_and_upper_exclusive(self):
        for value, label in (
            ("0", "F"),
            ("49.999", "F"),
            ("50", "C"),
            ("89.999", "B"),
            ("90", "A"),
            ("100", "A"),
        ):
            self.assertEqual(grade_for(Decimal(value), self.policy)[0], label)

    def test_negative_excess_and_nonfinite_marks_rejected(self):
        self.open()
        for value in ("-1", "100.001", "NaN", "Infinity", "1.0001"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self.mark(value)

    def test_nonassessed_status_never_accepts_numeric_marks(self):
        self.open()
        with self.assertRaisesMessage(ValidationError, "empty mark"):
            self.mark("0", "absent")

    def test_absent_is_incomplete_by_default(self):
        self.open()
        self.mark(None, "absent")
        result = calculate_candidate(self.candidate)
        self.assertEqual(result["outcome"], "incomplete")
        self.assertIsNone(result["percentage"])
        self.assertIsNone(result["obtained"])

    def test_explicit_absence_zero_policy_is_respected(self):
        self.policy.absence_rule = "zero"
        save_setup(self.admin, self.policy)
        self.open()
        self.mark(None, "absent")
        result = calculate_candidate(self.candidate)
        self.assertEqual(result["percentage"], "0.00")
        self.assertEqual(result["outcome"], "fail")

    def test_entirely_exempt_result_has_no_invented_percentage(self):
        self.open()
        self.mark(None, "exempt", remarks="Authorized fictional exemption")
        result = calculate_candidate(self.candidate)
        self.assertIsNone(result["percentage"])
        self.assertEqual(result["subjects"][0]["outcome"], "exempt")

    def test_pending_and_incomplete_are_not_zero(self):
        self.open()
        for status in ("pending", "incomplete"):
            self.mark(None, status, submit=False)
            result = calculate_candidate(self.candidate)
            self.assertIsNone(result["percentage"])
            self.assertEqual(result["outcome"], "incomplete")

    def test_draft_save_and_submit_are_distinct(self):
        self.open()
        self.mark(submit=False)
        self.assertEqual(self.sheet.state, "draft")
        self.mark()
        self.assertEqual(self.sheet.state, "submitted")
        with self.assertRaises(ValidationError):
            self.mark("81")

    def test_exact_roster_and_version_required(self):
        self.open()
        with self.assertRaisesMessage(ValidationError, "exact eligible roster"):
            save_marks(self.teacher, self.sheet.pk, {}, expected_version=0)
        self.mark(submit=False)
        with self.assertRaisesMessage(ValidationError, "Another user saved"):
            save_marks(self.teacher, self.sheet.pk, {}, expected_version=0)

    def test_teacher_cannot_enter_unassigned_subject_or_section(self):
        self.open()
        TeachingAssignment.objects.filter(teacher=self.data["teacher"]).delete()
        with self.assertRaises(PermissionDenied):
            self.mark()
        self.assertFalse(subjects_visible_to(self.teacher, self.session).exists())

    def test_student_guardian_and_accountant_cannot_enter_marks(self):
        self.open()
        for actor in (self.data["student_user"], self.data["parent"], self.data["accountant"]):
            with self.subTest(actor=actor), self.assertRaises(PermissionDenied):
                self.mark(actor=actor)

    def test_unassigned_controller_cannot_review_session(self):
        self.open()
        self.mark()
        self.assertFalse(sessions_visible_to(self.outsider).exists())
        with self.assertRaises(PermissionDenied):
            review_sheet(self.outsider, self.sheet.pk, "approve", expected_version=1, reason="Test")

    def test_independent_controller_cannot_approve_own_submission(self):
        self.open()
        self.mark(actor=self.admin)
        with self.assertRaisesMessage(ValidationError, "own submission"):
            review_sheet(self.admin, self.sheet.pk, "approve", expected_version=1, reason="Test")

    def test_returned_marks_can_be_corrected_and_resubmitted(self):
        self.open()
        self.mark()
        review_sheet(
            self.controller,
            self.sheet.pk,
            "return",
            expected_version=1,
            reason="Recheck question two",
        )
        self.mark("85")
        self.assertEqual(self.sheet.state, "submitted")
        self.assertIsNone(self.sheet.reviewed_by)

    def test_approval_requires_reviewed_sheets_and_principal_capability(self):
        self.open()
        self.action("close")
        with self.assertRaisesMessage(ValidationError, "Every marks sheet"):
            self.action("review", self.controller)
        with self.assertRaises(PermissionDenied):
            self.action("approve", self.admin)

    def test_publication_has_correct_marks_and_saved_policy(self):
        result = self.publish("79.125")
        self.assertEqual(result.data["percentage"], "79.13")
        self.assertEqual(result.data["grade"], "B")
        self.assertEqual(result.data["policy"]["name"], self.policy.name)
        self.assertEqual(result.data["approved_by"], self.principal.display_name)

    def test_draft_results_never_exposed_by_direct_urls(self):
        self.open()
        self.mark(submit=False)
        for actor in (self.data["student_user"], self.data["parent"]):
            self.client.force_login(actor, backend=BACKEND)
            self.assertEqual(
                self.client.get(f"/examinations/candidates/{self.candidate.pk}/").status_code, 404
            )
            self.assertEqual(
                self.client.get(f"/examinations/marks/{self.sheet.pk}/").status_code, 404
            )
            self.assertNotContains(self.client.get("/examinations/results/"), "80.00")

    def test_student_and_guardian_can_only_download_linked_reports(self):
        result = self.publish()
        unrelated = make_user("unrelatedlearner", "Student")
        for actor, expected in (
            (self.data["student_user"], 200),
            (self.data["parent"], 200),
            (unrelated, 404),
        ):
            self.client.force_login(actor, backend=BACKEND)
            self.assertEqual(
                self.client.get(f"/examinations/reports/{result.pk}/").status_code, expected
            )
            response = self.client.get(f"/examinations/reports/{result.pk}/?format=pdf")
            self.assertEqual(response.status_code, expected)
            if expected == 200:
                self.assertTrue(response.content.startswith(b"%PDF-"))

    def test_withheld_publication_contains_no_marks_or_remarks(self):
        self.open()
        self.mark("88", remarks="Restricted assessment narrative")
        self.approve_sheet()
        update_candidate(
            self.controller,
            self.candidate.pk,
            teacher_remarks="Restricted overall narrative",
            principal_remarks="",
            withheld=True,
            withholding_reason="Examination review",
            expected_version=self.session.version,
        )
        self.action("close")
        self.action("review", self.controller)
        self.action("approve", self.principal)
        self.action("publish")
        result = PublishedResult.objects.get(candidate=self.candidate)
        self.assertEqual(result.data["subjects"], [])
        self.assertEqual(result.data["teacher_remarks"], "")
        self.client.force_login(self.data["parent"], backend=BACKEND)
        response = self.client.get(f"/examinations/reports/{result.pk}/")
        self.assertContains(response, "Result withheld")
        self.assertNotContains(response, "Restricted assessment narrative")

    def test_guardian_unlink_revokes_html_pdf_and_notifications(self):
        result = self.publish()
        self.assertTrue(notifications_visible_to(self.data["parent"]).exists())
        GuardianStudent.objects.all().delete()
        self.client.force_login(self.data["parent"], backend=BACKEND)
        self.assertEqual(
            self.client.get(f"/examinations/reports/{result.pk}/?format=pdf").status_code, 404
        )
        self.assertFalse(notifications_visible_to(self.data["parent"]).exists())

    def test_correction_issues_new_snapshot_and_preserves_old(self):
        old = self.publish("80")
        entry = MarkEntry.objects.get(candidate=self.candidate)
        correction = request_correction(
            self.teacher,
            entry.pk,
            status="assessed",
            marks="90",
            remarks="Rechecked",
            reason="Question credit verified",
        )
        decide_correction(
            self.controller, correction.pk, approve=True, reason="Independent script review"
        )
        old.refresh_from_db()
        new = self.candidate.results.order_by("-publication__version").first()
        self.assertEqual(old.data["percentage"], "80.00")
        self.assertEqual(new.data["percentage"], "90.00")
        self.assertEqual(new.data["version"], 2)

    def test_self_correction_and_duplicate_decision_rejected(self):
        self.publish()
        entry = MarkEntry.objects.get(candidate=self.candidate)
        correction = request_correction(
            self.admin, entry.pk, status="assessed", marks="90", remarks="", reason="Recheck"
        )
        with self.assertRaises(ValidationError):
            decide_correction(self.admin, correction.pk, approve=True, reason="Own request")
        decide_correction(
            self.controller, correction.pk, approve=False, reason="No supporting evidence"
        )
        with self.assertRaises(ValidationError):
            decide_correction(self.controller, correction.pk, approve=True, reason="Duplicate")
        self.assertEqual(self.session.publications.count(), 1)

    def test_used_grade_policy_and_snapshots_are_database_protected(self):
        result = self.publish()
        for mutate in (
            lambda: GradingPolicy.objects.filter(pk=self.policy.pk).update(overall_pass=10),
            lambda: GradeBand.objects.filter(policy=self.policy).update(label="Changed"),
            lambda: PublishedResult.objects.filter(pk=result.pk).update(data={}),
            lambda: MarkEntry.objects.filter(candidate=self.candidate).update(marks=99),
        ):
            with (
                self.subTest(mutate=mutate),
                self.assertRaises(IntegrityError),
                transaction.atomic(),
            ):
                mutate()

    def test_database_checks_duplicate_and_range(self):
        self.open()
        self.mark(submit=False)
        entry = MarkEntry.objects.get(candidate=self.candidate)
        with self.assertRaises(IntegrityError), transaction.atomic():
            MarkEntry.objects.create(
                sheet=self.sheet,
                candidate=self.candidate,
                status="assessed",
                marks=50,
                changed_by=self.admin,
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            MarkEntry.objects.filter(pk=entry.pk).update(marks=101)

    def test_scheduling_class_room_and_invigilator_conflicts(self):
        room = save_setup(self.admin, ExamRoom(name="Room A"))
        save_schedule(
            self.admin,
            assessment_id=self.assessment.pk,
            starts_at=self.at(),
            ends_at=self.at(hour=10),
            room=room,
            invigilators=[self.data["teacher"]],
        )
        other = save_setup(
            self.admin,
            Assessment(
                exam_subject=self.subject,
                assessment_type=self.kind,
                name="Practical",
                max_marks=20,
                weight=10,
            ),
        )
        with self.assertRaises(ValidationError):
            save_schedule(
                self.admin,
                assessment_id=other.pk,
                starts_at=self.at(),
                ends_at=self.at(hour=10),
                room=room,
                invigilators=[self.data["teacher"]],
            )
        save_schedule(
            self.admin,
            assessment_id=other.pk,
            starts_at=self.at(hour=10),
            ends_at=self.at(hour=11),
            room=room,
            invigilators=[self.data["teacher"]],
        )

    def test_rankings_disabled_by_default_and_override_does_not_promote(self):
        result = self.publish()
        self.assertIsNone(result.data["rank"])
        original = Enrollment.objects.get(pk=self.candidate.enrollment_id)
        override_recommendation(
            self.principal, self.candidate.pk, eligible=False, reason="Academic review required"
        )
        original.refresh_from_db()
        self.assertTrue(original.is_active)
        self.assertEqual(original.section_id, self.data["section"].pk)

    def test_transfer_preserves_result_and_invalid_exit_is_rejected(self):
        result = self.publish()
        enrollment = self.candidate.enrollment
        with self.assertRaisesMessage(ValidationError, "examination roster"):
            transition_student(
                self.admin,
                self.data["own"].pk,
                action="withdraw",
                effective_on=DAY - timedelta(days=1),
                expected_enrollment=enrollment.pk,
            )
        transition_student(
            self.admin,
            self.data["own"].pk,
            action="transfer",
            effective_on=DAY + timedelta(days=1),
            expected_enrollment=enrollment.pk,
            academic_year=self.data["year"],
            section=self.data["other_section"],
        )
        result.refresh_from_db()
        self.assertEqual(result.data["section"], "A")

    def test_every_primary_screen_renders_and_csrf_blocks_mutations(self):
        self.publish()
        paths = [
            "/examinations/",
            "/examinations/setup/policies/",
            "/examinations/setup/bands/new/",
            f"/examinations/sessions/{self.session.pk}/",
            f"/examinations/marks/{self.sheet.pk}/",
            "/examinations/schedules/",
            "/examinations/results/",
            f"/examinations/candidates/{self.candidate.pk}/",
            f"/examinations/sessions/{self.session.pk}/analytics/",
            "/examinations/corrections/",
            "/examinations/notifications/",
        ]
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin, backend=BACKEND)
        self.assertEqual(
            client.post(
                f"/examinations/sessions/{self.session.pk}/actions/archive/", {}
            ).status_code,
            403,
        )
