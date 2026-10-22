from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse

from academics.models import Term
from attendance.calendar import SchoolCalendar
from attendance.exports import safe_csv
from attendance.forms import PolicyForm
from attendance.models import (
    AbsenceNotification,
    AttendanceCorrection,
    AttendancePolicy,
    CalendarEvent,
    LeaveRequest,
    StudentAttendance,
    StudentRegister,
)
from attendance.reporting import report_rows, summary
from attendance.selectors import (
    notifications_visible_to,
    staff_entries_visible_to,
    student_entries_visible_to,
)
from attendance.services import (
    decide_correction,
    decide_leave,
    request_correction,
    request_leave,
    save_policy,
    save_staff_register,
    save_student_register,
)
from people.models import Enrollment, Staff, Teacher
from people.services import transition_student

from .helpers import BACKEND, make_school_data, make_user

DAY = date(2026, 10, 5)
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=ZoneInfo("Asia/Karachi"))


class AttendanceFixtureMixin:
    @classmethod
    def setUpTestData(cls):
        cls.data = make_school_data()
        cls.actor = cls.data["admin"]
        cls.reviewer = make_user("attendanceprincipal", "Principal")
        cls.hr = make_user("attendancehr", "HR Manager")
        cls.staff = Staff.objects.create(
            user=cls.hr,
            employee_number="ATT-S1",
            first_name="Staff",
            last_name="Example",
            job_title="HR",
            joined_on=date(2026, 8, 1),
            department="Office",
        )
        Teacher.objects.filter(pk=cls.data["teacher"].pk).update(joined_on=date(2026, 8, 1))
        cls.data["teacher"].refresh_from_db()
        cls.policy = AttendancePolicy.objects.create(
            academic_year=cls.data["year"], effective_from=cls.data["year"].starts_on
        )

    def setUp(self):
        for name in (
            "attendance.services.school_now",
            "attendance.views.school_now",
            "attendance.calendar.school_now",
            "attendance.reporting.school_now",
            "attendance.forms.school_now",
        ):
            clock = patch(name, return_value=NOW)
            clock.start()
            self.addCleanup(clock.stop)
        self.client.force_login(self.actor, backend=BACKEND)

    def mark(
        self,
        status="present",
        *,
        day=DAY,
        actor=None,
        final=True,
        section=None,
        expected_version=0,
        arrival=None,
        notes="",
        student=None,
    ):
        section = section or self.data["section"]
        student = student or self.data["own"]
        enrollment = Enrollment.objects.get(
            student=student, academic_year=self.data["year"], section=section
        )
        return save_student_register(
            actor or self.actor,
            year_id=self.data["year"].pk,
            section_id=section.pk,
            day=day,
            rows={str(enrollment.pk): {"status": status, "arrival_time": arrival, "notes": notes}},
            expected_version=expected_version,
            final=final,
            reason="Authorized test backfill",
        )

    def staff_mark(self, statuses=None, *, final=True, day=DAY, actor=None, expected_version=0):
        statuses = statuses or {
            f"teacher:{self.data['teacher'].pk}": "present",
            f"staff:{self.staff.pk}": "present",
        }
        return save_staff_register(
            actor or self.actor,
            year_id=self.data["year"].pk,
            day=day,
            rows={key: {"status": value} for key, value in statuses.items()},
            expected_version=expected_version,
            final=final,
            reason="Authorized staff test backfill",
        )

    def report_data(self, **extra):
        return {"academic_year": self.data["year"], "period": "month", "date": DAY, **extra}


class AttendanceTests(AttendanceFixtureMixin, TestCase):
    def test_draft_and_final_states_and_incomplete_detection(self):
        draft = self.mark("", final=False)
        self.assertEqual(draft.state, "draft")
        self.assertFalse(student_entries_visible_to(self.data["student_user"]).exists())
        with self.assertRaises(ValidationError):
            self.mark("", expected_version=draft.version)
        draft.refresh_from_db()
        self.assertEqual(draft.state, "draft")
        final = self.mark(expected_version=draft.version)
        self.assertEqual(final.state, "final")
        self.assertEqual(student_entries_visible_to(self.data["student_user"]).count(), 1)

    def test_duplicate_register_and_student_date_constraints(self):
        register = self.mark()
        with self.assertRaises(IntegrityError), transaction.atomic():
            StudentRegister.objects.create(
                academic_year=self.data["year"],
                section=self.data["section"],
                attendance_on=DAY,
                policy=self.policy,
                created_by=self.actor,
                updated_by=self.actor,
            )
        with self.assertRaises(ValidationError):
            self.mark(expected_version=register.version)

    def test_stale_draft_rejected(self):
        draft = self.mark(final=False)
        with self.assertRaises(ValidationError):
            self.mark(final=False, expected_version=0)
        self.assertEqual(draft.entries.count(), 1)

    def test_teacher_can_mark_only_assigned_section_and_year(self):
        self.mark(actor=self.data["teacher_user"])
        with self.assertRaises(PermissionDenied):
            self.mark(
                actor=self.data["teacher_user"],
                section=self.data["other_section"],
                student=self.data["other"],
            )
        with self.assertRaises(PermissionDenied):
            save_student_register(
                self.data["teacher_user"],
                year_id=self.data["old_year"].pk,
                section_id=self.data["other_section"].pk,
                day=date(2026, 6, 1),
                rows={},
            )

    def test_students_guardians_and_finance_cannot_mark(self):
        for key in ("student_user", "parent", "accountant"):
            with self.subTest(key=key), self.assertRaises(PermissionDenied):
                self.mark(actor=self.data[key])

    def test_dated_enrollment_prevents_out_of_range_and_forged_rosters(self):
        with self.assertRaises(ValidationError):
            self.mark(day=date(2026, 7, 31))
        with self.assertRaises(ValidationError):
            save_student_register(
                self.actor,
                year_id=self.data["year"].pk,
                section_id=self.data["section"].pk,
                day=DAY,
                rows={"999999": {"status": "present"}},
                final=True,
            )
        register = StudentRegister.objects.create(
            academic_year=self.data["year"],
            section=self.data["section"],
            attendance_on=DAY,
            policy=self.policy,
            created_by=self.actor,
            updated_by=self.actor,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            StudentAttendance.objects.create(
                register=register,
                enrollment=self.data["other"].enrollments.get(is_active=True),
                student=self.data["other"],
                attendance_on=DAY,
                status="present",
                recorded_by=self.actor,
            )

    def test_final_rows_registers_and_decisions_are_immutable(self):
        register = self.mark()
        entry = register.entries.get()
        for operation in (
            lambda: StudentAttendance.objects.filter(pk=entry.pk).update(status="absent"),
            lambda: entry.delete(),
            lambda: StudentRegister.objects.filter(pk=register.pk).update(
                state="draft", submitted_by=None, submitted_at=None
            ),
            lambda: register.delete(),
        ):
            with (
                self.subTest(operation=operation),
                self.assertRaises(IntegrityError),
                transaction.atomic(),
            ):
                operation()

    def test_direct_finalization_requires_complete_roster(self):
        register = StudentRegister.objects.create(
            academic_year=self.data["year"],
            section=self.data["section"],
            attendance_on=DAY,
            policy=self.policy,
            created_by=self.actor,
            updated_by=self.actor,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            StudentRegister.objects.filter(pk=register.pk).update(
                state="final", submitted_by=self.actor, submitted_at=NOW
            )

    def test_holidays_weekends_and_term_gaps_are_excluded(self):
        for day in (date(2026, 10, 3), date(2026, 10, 4)):
            with self.assertRaises(ValidationError):
                self.mark(day=day)
        CalendarEvent.objects.create(
            academic_year=self.data["year"],
            title="Fictional public holiday",
            kind="public",
            starts_on=DAY,
            ends_on=DAY,
            reason="Calendar test",
            created_by=self.actor,
        )
        with self.assertRaises(ValidationError):
            self.mark()
        Term.objects.create(
            academic_year=self.data["year"],
            name="Future term",
            starts_on=date(2026, 11, 1),
            ends_on=date(2026, 12, 31),
        )
        self.assertEqual(
            SchoolCalendar(self.data["year"]).reason(date(2026, 10, 6)), "Outside academic terms"
        )

    def test_additional_working_day(self):
        day = date(2026, 10, 3)
        CalendarEvent.objects.create(
            academic_year=self.data["year"],
            title="Fictional Saturday class",
            kind="working",
            starts_on=day,
            ends_on=day,
            reason="Working day test",
            created_by=self.actor,
        )
        self.mark(day=day)
        self.assertEqual(StudentAttendance.objects.count(), 1)

    def test_late_arrival_rules_and_excused_reason(self):
        register = self.mark(arrival=time(8, 1))
        self.assertEqual(register.entries.get().status, "late")
        with self.assertRaises(ValidationError):
            self.mark("excused", day=date(2026, 10, 2))

    def test_teacher_cutoff_admin_reason_and_future_denial(self):
        with patch("attendance.services.school_now", return_value=NOW.replace(hour=18)):
            with self.assertRaises(ValidationError):
                self.mark(actor=self.data["teacher_user"])
        with self.assertRaises(ValidationError):
            self.mark(day=DAY + timedelta(days=1))
        enrollment = self.data["own"].enrollments.get(is_active=True)
        with self.assertRaises(ValidationError):
            save_student_register(
                self.actor,
                year_id=self.data["year"].pk,
                section_id=self.data["section"].pk,
                day=date(2026, 10, 2),
                rows={str(enrollment.pk): {"status": "present"}},
                final=True,
            )

    def test_percentage_weights_excused_and_missing(self):
        self.mark("present", day=date(2026, 9, 28))
        self.mark("absent", day=date(2026, 9, 29))
        self.mark("late", day=date(2026, 9, 30))
        self.mark("excused", day=date(2026, 10, 1), notes="Authorized excuse")
        self.mark("", day=date(2026, 10, 2), final=False)
        rows, *_ = report_rows(self.actor, self.report_data(period="year"))
        result = summary(rows)
        self.assertEqual(result["denominator"], 3)
        self.assertEqual(result["percentage"], Decimal("66.67"))
        self.assertEqual(result["absent"], 1)

    def test_nondefault_late_and_excused_policy(self):
        self.policy.late_credit = Decimal("0.5")
        self.policy.exclude_excused = False
        self.policy.save()
        self.mark("late", day=date(2026, 10, 1))
        self.mark("excused", day=date(2026, 10, 2), notes="Authorized excuse")
        rows, *_ = report_rows(self.actor, self.report_data())
        self.assertEqual(summary(rows)["percentage"], Decimal("25.00"))

    def test_missing_attendance_has_no_percentage(self):
        rows, *_ = report_rows(self.actor, self.report_data())
        self.assertIsNone(summary(rows)["percentage"])
        self.assertEqual(summary(rows)["absent"], 0)

    def test_retroactive_holiday_retains_records_but_excludes_percentage(self):
        self.mark("absent")
        CalendarEvent.objects.create(
            academic_year=self.data["year"],
            title="Unexpected closure",
            kind="closure",
            starts_on=DAY,
            ends_on=DAY,
            reason="Fictional emergency closure",
            created_by=self.actor,
        )
        rows, *_ = report_rows(self.actor, self.report_data())
        self.assertEqual(rows.count(), 0)
        self.assertEqual(StudentAttendance.objects.count(), 1)

    def test_student_guardian_and_teacher_scopes(self):
        self.mark("absent")
        self.mark("present", section=self.data["other_section"], student=self.data["other"])
        for key in ("student_user", "parent", "teacher_user"):
            with self.subTest(key=key):
                self.assertEqual(student_entries_visible_to(self.data[key]).count(), 1)
                self.client.force_login(self.data[key], backend=BACKEND)
                self.assertEqual(
                    self.client.get(
                        reverse("attendance:student", args=[self.data["other"].pk])
                    ).status_code,
                    404,
                )
        self.data["guardian"].student_links.all().delete()
        self.assertFalse(student_entries_visible_to(self.data["parent"]).exists())

    def test_transfer_retains_attendance_and_prevents_invalid_backdating(self):
        self.mark()
        current = self.data["own"].enrollments.get(is_active=True)
        with self.assertRaises(ValidationError):
            transition_student(
                self.actor,
                self.data["own"].pk,
                action="transfer",
                effective_on=date(2026, 10, 2),
                expected_enrollment=current.pk,
                academic_year=self.data["year"],
                section=self.data["other_section"],
            )
        transition_student(
            self.actor,
            self.data["own"].pk,
            action="transfer",
            effective_on=DAY,
            expected_enrollment=current.pk,
            academic_year=self.data["year"],
            section=self.data["other_section"],
        )
        self.assertEqual(student_entries_visible_to(self.data["student_user"]).count(), 1)

    def test_draft_notifications_never_send_and_final_only_correct_guardian(self):
        draft = self.mark("absent", final=False)
        self.assertFalse(AbsenceNotification.objects.exists())
        self.mark("absent", expected_version=draft.version)
        self.assertEqual(AbsenceNotification.objects.count(), 1)
        self.assertEqual(notifications_visible_to(self.data["parent"]).count(), 1)
        self.assertFalse(notifications_visible_to(self.data["student_user"]).exists())

    def test_correction_approval_history_and_notifications(self):
        entry = self.mark("absent").entries.get()
        correction = request_correction(
            self.data["teacher_user"],
            kind="student",
            entry_id=entry.pk,
            values={"status": "present"},
            reason="Register checked with class teacher",
        )
        entry.refresh_from_db()
        self.assertEqual(entry.status, "absent")
        decide_correction(self.reviewer, correction.pk, approve=True)
        entry.refresh_from_db()
        self.assertEqual(entry.status, "present")
        self.assertEqual(entry.revision, 1)
        correction.refresh_from_db()
        self.assertEqual(correction.before["status"], "absent")
        self.assertEqual(correction.after["status"], "present")
        self.assertEqual(AbsenceNotification.objects.get().state, "superseded")
        with self.assertRaises(IntegrityError), transaction.atomic():
            AttendanceCorrection.objects.filter(pk=correction.pk).update(reason="Rewritten")

    def test_correction_reason_rejection_self_approval_and_window(self):
        entry = self.mark().entries.get()
        with self.assertRaises(ValidationError):
            request_correction(
                self.data["teacher_user"],
                kind="student",
                entry_id=entry.pk,
                values={"status": "absent"},
                reason="",
            )
        correction = request_correction(
            self.reviewer,
            kind="student",
            entry_id=entry.pk,
            values={"status": "absent"},
            reason="Review attendance",
        )
        with self.assertRaises(ValidationError):
            decide_correction(self.reviewer, correction.pk, approve=True)
        with self.assertRaises(ValidationError):
            decide_correction(self.actor, correction.pk, approve=False)
        decide_correction(self.actor, correction.pk, approve=False, reason="No supporting record")
        entry.refresh_from_db()
        self.assertEqual(entry.status, "present")
        with (
            patch("attendance.services.school_now", return_value=NOW + timedelta(days=8)),
            self.assertRaises(ValidationError),
        ):
            request_correction(
                self.data["teacher_user"],
                kind="student",
                entry_id=entry.pk,
                values={"status": "absent"},
                reason="Outside the window",
            )

    def test_unrelated_teacher_and_student_cannot_request_or_approve(self):
        entry = self.mark(
            section=self.data["other_section"], student=self.data["other"]
        ).entries.get()
        for actor in (self.data["teacher_user"], self.data["student_user"], self.data["parent"]):
            with self.subTest(actor=actor.pk), self.assertRaises(PermissionDenied):
                request_correction(
                    actor,
                    kind="student",
                    entry_id=entry.pk,
                    values={"status": "absent"},
                    reason="Unauthorized",
                )

    def test_staff_statuses_self_scope_and_unique_register(self):
        register = self.staff_mark(
            {f"teacher:{self.data['teacher'].pk}": "half_day", f"staff:{self.staff.pk}": "duty"}
        )
        self.assertEqual(register.entries.count(), 2)
        self.assertEqual(staff_entries_visible_to(self.data["teacher_user"]).count(), 1)
        self.assertEqual(staff_entries_visible_to(self.hr).count(), 2)
        rows, *_ = report_rows(self.actor, self.report_data(), staff=True)
        self.assertEqual(summary(rows, staff=True)["percentage"], Decimal("75.00"))
        with self.assertRaises(ValidationError):
            self.staff_mark(expected_version=register.version)

    def test_staff_cannot_mark_own_register(self):
        with self.assertRaises(PermissionDenied):
            self.staff_mark(actor=self.data["teacher_user"])

    def test_staff_leave_and_closure_require_supporting_records(self):
        with self.assertRaises(ValidationError):
            self.staff_mark(
                {f"teacher:{self.data['teacher'].pk}": "leave", f"staff:{self.staff.pk}": "present"}
            )
        CalendarEvent.objects.create(
            academic_year=self.data["year"],
            title="Closure test",
            kind="closure",
            starts_on=DAY,
            ends_on=DAY,
            reason="Fictional closure",
            created_by=self.actor,
        )
        register = self.staff_mark(
            {f"teacher:{self.data['teacher'].pk}": "closure", f"staff:{self.staff.pk}": "closure"}
        )
        rows, *_ = report_rows(self.actor, self.report_data(), staff=True)
        self.assertEqual(rows.count(), 0)
        self.assertEqual(register.entries.count(), 2)

    def test_leave_approval_rejection_overlap_and_history(self):
        leave = request_leave(
            self.data["teacher_user"],
            year_id=self.data["year"].pk,
            person=self.data["teacher"],
            starts_on=DAY,
            ends_on=DAY,
            kind="sick",
            reason="Fictional sick leave",
        )
        with self.assertRaises(ValidationError):
            request_leave(
                self.data["teacher_user"],
                year_id=self.data["year"].pk,
                person=self.data["teacher"],
                starts_on=DAY,
                ends_on=DAY,
                kind="casual",
                reason="Overlapping request",
            )
        decide_leave(self.hr, leave.pk, approve=True)
        self.staff_mark(
            {f"teacher:{self.data['teacher'].pk}": "leave", f"staff:{self.staff.pk}": "present"}
        )
        rows, *_ = report_rows(self.actor, self.report_data(), staff=True)
        self.assertEqual(summary(rows, staff=True)["denominator"], 1)
        self.assertEqual(summary(rows, staff=True)["absent"], 0)

    def test_leave_approval_corrects_finalized_absence_with_history(self):
        register = self.staff_mark(
            {f"teacher:{self.data['teacher'].pk}": "absent", f"staff:{self.staff.pk}": "present"}
        )
        leave = request_leave(
            self.data["teacher_user"],
            year_id=self.data["year"].pk,
            person=self.data["teacher"],
            starts_on=DAY,
            ends_on=DAY,
            kind="sick",
            reason="Fictional retrospective sick leave",
        )
        decide_leave(self.hr, leave.pk, approve=True)
        entry = register.entries.get(teacher=self.data["teacher"])
        self.assertEqual(entry.status, "leave")
        correction = entry.corrections.get()
        self.assertEqual(correction.before["status"], "absent")
        self.assertEqual(correction.after["status"], "leave")

    def test_leave_self_approval_and_other_employee_denied(self):
        with self.assertRaises(PermissionDenied):
            request_leave(
                self.data["teacher_user"],
                year_id=self.data["year"].pk,
                person=self.staff,
                starts_on=DAY,
                ends_on=DAY,
                kind="sick",
                reason="Unrelated",
            )
        leave = request_leave(
            self.hr,
            year_id=self.data["year"].pk,
            person=self.staff,
            starts_on=DAY,
            ends_on=DAY,
            kind="casual",
            reason="Fictional HR leave",
        )
        with self.assertRaises(ValidationError):
            decide_leave(self.hr, leave.pk, approve=True)
        decide_leave(
            self.actor, leave.pk, approve=False, reason="Request rejected with explanation"
        )
        self.assertEqual(LeaveRequest.objects.get(pk=leave.pk).state, "rejected")

    def test_policy_in_use_protected_and_revision_changes_future_only(self):
        self.mark()
        with self.assertRaises(IntegrityError), transaction.atomic():
            AttendancePolicy.objects.filter(pk=self.policy.pk).update(late_credit=Decimal("0.5"))
        form = PolicyForm(
            {
                "academic_year": self.data["year"].pk,
                "effective_from": "2026-10-06",
                "working_weekdays": [0, 1, 2, 3, 4],
                "late_after": "08:00",
                "cutoff_time": "17:00",
                "late_credit": "0.5",
                "correction_window_days": "7",
                "low_attendance_threshold": "75",
                "exclude_excused": "on",
                "enforce_terms": "on",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        revised = save_policy(self.actor, form)
        self.assertEqual(revised.effective_from, DAY + timedelta(days=1))

    def test_csrf_and_unauthorized_direct_urls(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.actor, backend=BACKEND)
        self.assertEqual(client.post("/attendance/register/", {}).status_code, 403)
        for key in ("student_user", "parent", "accountant"):
            self.client.force_login(self.data[key], backend=BACKEND)
            for url in (
                "/attendance/register/",
                "/attendance/staff/register/",
                "/attendance/settings/",
                "/attendance/settings/policy/new/",
            ):
                with self.subTest(key=key, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)
                    self.assertEqual(
                        self.client.post(url, {}).status_code,
                        405 if url == "/attendance/settings/" else 403,
                    )

    def test_html_csv_pdf_export_scope_and_formula_escaping(self):
        self.mark("absent")
        self.mark("present", section=self.data["other_section"], student=self.data["other"])
        self.client.force_login(self.data["student_user"], backend=BACKEND)
        params = {"academic_year": self.data["year"].pk, "date": "2026-10-05", "period": "month"}
        for kind in ("csv", "pdf", "print"):
            with self.subTest(kind=kind):
                response = self.client.get(
                    "/attendance/reports/students/", {**params, "format": kind}
                )
                self.assertEqual(response.status_code, 200)
                if kind == "pdf":
                    self.assertTrue(response.content.startswith(b"%PDF-"))
                    self.assertEqual(response["Content-Type"], "application/pdf")
                else:
                    self.assertNotIn(b"TEST-002", response.content)
        self.assertEqual(safe_csv("  =SUM(A1:A2)"), "'  =SUM(A1:A2)")
        self.assertEqual(
            self.client.get("/attendance/reports/staff/", {**params, "format": "pdf"}).status_code,
            403,
        )

    def test_all_screens_render_and_unsubmitted_not_absent(self):
        self.mark()
        self.staff_mark()
        urls = [
            "/attendance/",
            "/attendance/staff/",
            "/attendance/register/",
            "/attendance/staff/register/",
            "/attendance/settings/",
            "/attendance/settings/policy/new/",
            "/attendance/settings/calendar/new/",
            "/attendance/corrections/",
            "/attendance/leave/",
            "/attendance/leave/new/",
            "/attendance/notifications/",
            f"/attendance/students/{self.data['own'].pk}/",
            f"/attendance/employees/teacher/{self.data['teacher'].pk}/",
        ]
        urls += [
            f"/attendance/reports/{kind}/"
            for kind in (
                "students",
                "summary",
                "classes",
                "low",
                "staff",
                "staff-summary",
                "departments",
                "staff-absences",
            )
        ]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
        response = self.client.get(
            "/attendance/", {"academic_year": self.data["year"].pk, "date": DAY.isoformat()}
        )
        self.assertEqual(response.context["stats"]["absent"], 0)
        self.assertEqual(len(response.context["missing"]), 1)
