import io
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from attendance.calendar import SchoolCalendar, school_now
from attendance.models import (
    AbsenceNotification,
    AttendancePolicy,
    CalendarEvent,
    LeaveRequest,
    StaffAttendance,
    StudentAttendance,
    StudentRegister,
)
from attendance.selectors import enrollment_roster, notifications_visible_to, staff_roster
from attendance.services import (
    cancel_calendar_event,
    decide_correction,
    decide_leave,
    request_correction,
    request_leave,
    save_staff_register,
    save_student_register,
    sync_notifications,
)
from core.models import SchoolSettings
from people.models import Enrollment, Guardian, GuardianStudent, Staff, Student, Teacher

from .helpers import BACKEND, PASSWORD, make_user
from .test_attendance import DAY, NOW, AttendanceFixtureMixin


class AttendanceBoundaryTests(AttendanceFixtureMixin, TestCase):
    def test_notification_identity_and_history_are_database_protected(self):
        self.mark("absent")
        notice = AbsenceNotification.objects.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            AbsenceNotification.objects.filter(pk=notice.pk).update(recipient=self.reviewer)
        with self.assertRaises(IntegrityError), transaction.atomic():
            notice.delete()

    def test_database_rejects_future_register_even_with_valid_future_year(self):
        from django.utils import timezone

        from academics.models import AcademicYear

        start = timezone.now().date() + timedelta(days=30)
        year = AcademicYear.objects.create(
            name="Future attendance guard", starts_on=start, ends_on=start + timedelta(days=30)
        )
        policy = AttendancePolicy.objects.create(academic_year=year, effective_from=start)
        with self.assertRaises(IntegrityError), transaction.atomic():
            StudentRegister.objects.create(
                academic_year=year,
                policy=policy,
                section=self.data["section"],
                attendance_on=start,
                created_by=self.actor,
                updated_by=self.actor,
            )

    def test_calendar_cancellation_retains_history_and_requires_reason(self):
        event = CalendarEvent.objects.create(
            academic_year=self.data["year"],
            title="Calendar correction",
            kind="school",
            starts_on=DAY,
            ends_on=DAY,
            reason="Fictional holiday",
            created_by=self.actor,
        )
        self.assertTrue(SchoolCalendar(self.data["year"]).reason(DAY))
        with self.assertRaises(ValidationError):
            cancel_calendar_event(self.actor, event.pk, "")
        cancel_calendar_event(
            self.actor, event.pk, "Incorrect date, corrected with school approval"
        )
        event.refresh_from_db()
        self.assertTrue(event.is_cancelled)
        self.assertEqual(event.cancelled_by, self.actor)
        self.assertFalse(SchoolCalendar(self.data["year"]).reason(DAY))
        with self.assertRaises(IntegrityError), transaction.atomic():
            CalendarEvent.objects.filter(pk=event.pk).update(title="Erase original")

    def test_policy_weekday_shape_and_credit_database_constraints(self):
        for changes in (
            {"working_weekdays": [7]},
            {"working_weekdays": []},
            {"late_credit": Decimal("1.01")},
            {"cutoff_time": "07:00"},
        ):
            with (
                self.subTest(changes=changes),
                self.assertRaises(IntegrityError),
                transaction.atomic(),
            ):
                AttendancePolicy.objects.filter(pk=self.policy.pk).update(**changes)

    def test_school_timezone_controls_local_date(self):
        SchoolSettings.objects.create(timezone="Pacific/Kiritimati")
        # Call the original function; fixture clocks are intentionally fixed elsewhere.
        with patch(
            "attendance.calendar.timezone.now",
            return_value=datetime(2026, 10, 22, 15, tzinfo=ZoneInfo("UTC")),
        ):
            self.assertEqual(school_now().date(), date(2026, 10, 23))

    def test_staff_draft_incomplete_and_wrong_person_roster(self):
        draft = self.staff_mark(
            {f"teacher:{self.data['teacher'].pk}": "", f"staff:{self.staff.pk}": "present"},
            final=False,
        )
        with self.assertRaises(ValidationError):
            self.staff_mark(
                {f"teacher:{self.data['teacher'].pk}": "", f"staff:{self.staff.pk}": "present"},
                expected_version=draft.version,
            )
        with self.assertRaises(ValidationError):
            save_staff_register(
                self.actor,
                year_id=self.data["year"].pk,
                day=DAY,
                rows={"teacher:99999": {"status": "present"}},
                expected_version=draft.version,
            )

    def test_direct_staff_history_and_employment_dates_protected(self):
        register = self.staff_mark()
        entry = register.entries.get(teacher=self.data["teacher"])
        with self.assertRaises(IntegrityError), transaction.atomic():
            StaffAttendance.objects.filter(pk=entry.pk).update(status="absent")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Teacher.objects.filter(pk=self.data["teacher"].pk).update(
                joined_on=DAY + timedelta(days=1)
            )

    def test_one_account_has_one_canonical_employee_roster(self):
        duplicate = Staff.objects.create(
            user=self.data["teacher_user"],
            first_name="Same",
            last_name="Employee",
            employee_number="ALT-T1",
            job_title="Dual role",
            joined_on=self.data["year"].starts_on,
        )
        self.assertNotIn(f"staff:{duplicate.pk}", dict(staff_roster(DAY)))
        with self.assertRaises(ValidationError):
            request_leave(
                self.data["teacher_user"],
                year_id=self.data["year"].pk,
                person=duplicate,
                starts_on=DAY,
                ends_on=DAY,
                kind="sick",
                reason="Use the canonical profile",
            )

    def test_multiple_guardians_children_notification_deduplication(self):
        other_parent = make_user("attendanceparent2", "Parent or Guardian")
        guardian = Guardian.objects.create(
            user=other_parent, first_name="Second", last_name="Guardian"
        )
        GuardianStudent.objects.create(
            guardian=guardian, student=self.data["own"], relationship="Parent"
        )
        GuardianStudent.objects.create(
            guardian=self.data["guardian"], student=self.data["other"], relationship="Parent"
        )
        entry = self.mark("absent").entries.get()
        self.mark("absent", section=self.data["other_section"], student=self.data["other"])
        sync_notifications(entry)
        sync_notifications(entry)
        self.assertEqual(AbsenceNotification.objects.count(), 3)
        self.assertEqual(notifications_visible_to(self.data["parent"]).count(), 2)
        self.assertEqual(notifications_visible_to(other_parent).count(), 1)

    def test_guardian_unlink_immediately_revokes_notification_url(self):
        self.mark("absent")
        notice = AbsenceNotification.objects.get()
        self.client.force_login(self.data["parent"], backend=BACKEND)
        self.assertEqual(
            self.client.post(reverse("attendance:notification_read", args=[notice.pk])).status_code,
            302,
        )
        self.data["guardian"].student_links.all().delete()
        self.assertFalse(notifications_visible_to(self.data["parent"]).exists())
        self.assertEqual(
            self.client.post(reverse("attendance:notification_read", args=[notice.pk])).status_code,
            404,
        )

    def test_new_absence_after_correction_gets_new_notification_revision(self):
        entry = self.mark().entries.get()
        correction = request_correction(
            self.data["teacher_user"],
            kind="student",
            entry_id=entry.pk,
            values={"status": "absent"},
            reason="Reconciled classroom record",
        )
        decide_correction(self.reviewer, correction.pk, approve=True)
        self.assertEqual(AbsenceNotification.objects.get().revision, 1)
        entry.refresh_from_db()
        correction = request_correction(
            self.data["teacher_user"],
            kind="student",
            entry_id=entry.pk,
            values={"status": "present"},
            reason="Further authorized evidence",
        )
        decide_correction(self.reviewer, correction.pk, approve=True)
        self.assertEqual(AbsenceNotification.objects.get().state, "superseded")

    def test_custom_approval_permission_does_not_grant_global_oversight(self):
        entry = self.mark().entries.get()
        correction = request_correction(
            self.actor,
            kind="student",
            entry_id=entry.pk,
            values={"status": "absent"},
            reason="Review requested",
        )
        teacher = self.data["teacher_user"]
        teacher.user_permissions.add(Permission.objects.get(codename="approve_correction"))
        with self.assertRaises(PermissionDenied):
            decide_correction(teacher, correction.pk, approve=True)

    def test_own_staff_correction_and_unrelated_employee_denial(self):
        register = self.staff_mark()
        own = register.entries.get(teacher=self.data["teacher"])
        other = register.entries.get(staff=self.staff)
        correction = request_correction(
            self.data["teacher_user"],
            kind="staff",
            entry_id=own.pk,
            values={"status": "late"},
            reason="Recorded arrival was late",
        )
        decide_correction(self.hr, correction.pk, approve=True)
        own.refresh_from_db()
        self.assertEqual(own.status, "late")
        with self.assertRaises(PermissionDenied):
            request_correction(
                self.data["teacher_user"],
                kind="staff",
                entry_id=other.pk,
                values={"status": "late"},
                reason="Unrelated employee",
            )

    def test_leave_approval_outside_window_rolls_back_decision(self):
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
            reason="Late leave request",
        )
        with (
            patch("attendance.services.school_now", return_value=NOW + timedelta(days=8)),
            self.assertRaises(ValidationError),
        ):
            decide_leave(self.hr, leave.pk, approve=True)
        self.assertEqual(LeaveRequest.objects.get(pk=leave.pk).state, "pending")
        self.assertEqual(register.entries.get(teacher=self.data["teacher"]).status, "absent")

    def test_register_http_flow_confirmation_and_stale_form(self):
        enrollment = self.data["own"].enrollments.get(is_active=True)
        values = {
            "academic_year": self.data["year"].pk,
            "section": self.data["section"].pk,
            "date": DAY.isoformat(),
            "expected_version": 0,
            "action": "draft",
            "rows-TOTAL_FORMS": "1",
            "rows-INITIAL_FORMS": "1",
            "rows-MIN_NUM_FORMS": "0",
            "rows-MAX_NUM_FORMS": "2000",
            "rows-0-key": str(enrollment.pk),
            "rows-0-status": "present",
        }
        response = self.client.post("/attendance/register/", values)
        self.assertEqual(response.status_code, 302)
        register = StudentRegister.objects.get(attendance_on=DAY)
        response = self.client.post(
            "/attendance/register/",
            {**values, "expected_version": register.version, "action": "final"},
        )
        self.assertContains(response, "Confirm the register")
        response = self.client.post(
            "/attendance/register/",
            {**values, "expected_version": register.version, "action": "final", "confirm": "on"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(StudentRegister.objects.get(pk=register.pk).state, "final")

    def test_staff_register_http_and_calendar_cancel_screen(self):
        teacher, staff = self.data["teacher"], self.staff
        values = {
            "academic_year": self.data["year"].pk,
            "date": DAY.isoformat(),
            "expected_version": 0,
            "action": "final",
            "confirm": "on",
            "rows-TOTAL_FORMS": "2",
            "rows-INITIAL_FORMS": "2",
            "rows-MIN_NUM_FORMS": "0",
            "rows-MAX_NUM_FORMS": "1000",
            "rows-0-key": f"teacher:{teacher.pk}",
            "rows-0-status": "present",
            "rows-1-key": f"staff:{staff.pk}",
            "rows-1-status": "present",
        }
        self.assertEqual(self.client.post("/attendance/staff/register/", values).status_code, 302)
        event = CalendarEvent.objects.create(
            academic_year=self.data["year"],
            title="Cancel example",
            kind="school",
            starts_on=DAY,
            ends_on=DAY,
            reason="Fictional",
            created_by=self.actor,
        )
        self.assertEqual(
            self.client.get(reverse("attendance:calendar_cancel", args=[event.pk])).status_code, 200
        )
        self.assertEqual(
            self.client.post(
                reverse("attendance:calendar_cancel", args=[event.pk]),
                {"reason": "Correction to calendar", "confirm": "on"},
            ).status_code,
            302,
        )

    def test_report_day_week_year_low_and_foreign_filter_isolation(self):
        self.mark("absent")
        self.client.force_login(self.data["student_user"], backend=BACKEND)
        for period in ("day", "week", "month", "year"):
            response = self.client.get(
                "/attendance/reports/summary/",
                {"academic_year": self.data["year"].pk, "date": DAY.isoformat(), "period": period},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context["stats"]["absent"], 1)
        response = self.client.get(
            "/attendance/reports/low/",
            {"academic_year": self.data["year"].pk, "date": DAY.isoformat()},
        )
        self.assertEqual(len(response.context["rows"]), 1)
        self.assertEqual(
            self.client.get(
                "/attendance/reports/students/", {"student": self.data["other"].pk, "format": "pdf"}
            ).status_code,
            400,
        )

    def test_employee_report_filter_and_staff_person_pdf_link(self):
        self.staff_mark()
        self.client.force_login(self.data["teacher_user"], backend=BACKEND)
        response = self.client.get(
            "/attendance/reports/staff/",
            {
                "academic_year": self.data["year"].pk,
                "date": DAY.isoformat(),
                "format": "csv",
                "employee": f"teacher:{self.data['teacher'].pk}",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"Staff Example", response.content)
        self.assertEqual(
            self.client.get(
                "/attendance/reports/staff/",
                {"employee": f"staff:{self.staff.pk}", "format": "pdf"},
            ).status_code,
            400,
        )

    def test_register_query_count_does_not_grow_per_student(self):
        self.actor.has_perm("attendance.mark_attendance")

        def measured(day):
            roster = list(enrollment_roster(self.data["year"], self.data["section"], day))
            with CaptureQueriesContext(connection) as queries:
                save_student_register(
                    self.actor,
                    year_id=self.data["year"].pk,
                    section_id=self.data["section"].pk,
                    day=day,
                    rows={str(e.pk): {"status": "present"} for e in roster},
                    final=False,
                )
            return len(queries)

        first = measured(date(2026, 10, 1))
        for index in range(20):
            student = Student.objects.create(
                first_name="Scale", last_name=str(index), admission_number=f"SCALE-{index}"
            )
            Enrollment.objects.create(
                student=student,
                academic_year=self.data["year"],
                section=self.data["section"],
                started_on=self.data["year"].starts_on,
            )
        self.assertLessEqual(measured(date(2026, 10, 2)), first + 2)

    def test_print_report_includes_all_rows_not_only_first_page(self):
        days = SchoolCalendar(self.data["year"]).working_dates(self.data["year"].starts_on, DAY)[
            :35
        ]
        for day in days:
            self.mark(day=day)
        response = self.client.get(
            "/attendance/reports/students/",
            {"academic_year": self.data["year"].pk, "period": "year", "format": "print"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["rows"]), 35)

    def test_fictional_demo_is_repeatable_and_preserves_existing_register(self):
        with (
            override_settings(DEBUG=True, ALLOW_DEMO_DATA=True),
            patch.dict("os.environ", {"DEMO_PASSWORD": PASSWORD}),
        ):
            call_command("seed_demo", stdout=io.StringIO())
            counts = (
                StudentRegister.objects.count(),
                StudentAttendance.objects.count(),
                StaffAttendance.objects.count(),
                AbsenceNotification.objects.count(),
            )
            first = (
                StudentAttendance.objects.filter(student__admission_number__startswith="DEMO-")
                .order_by("pk")
                .first()
            )
            saved = (first.status, first.revision, first.updated_at)
            call_command("seed_demo", stdout=io.StringIO())
        self.assertEqual(
            counts,
            (
                StudentRegister.objects.count(),
                StudentAttendance.objects.count(),
                StaffAttendance.objects.count(),
                AbsenceNotification.objects.count(),
            ),
        )
        first.refresh_from_db()
        self.assertEqual(saved, (first.status, first.revision, first.updated_at))
