from datetime import time
from decimal import Decimal

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateRangeField
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from core.models import TimestampedModel


class StudentStatus(models.TextChoices):
    PRESENT = "present", "Present"
    ABSENT = "absent", "Absent"
    LATE = "late", "Late"
    EXCUSED = "excused", "Excused"


class StaffStatus(models.TextChoices):
    PRESENT = "present", "Present"
    ABSENT = "absent", "Absent"
    LATE = "late", "Late"
    HALF = "half_day", "Half-day"
    LEAVE = "leave", "Approved leave"
    DUTY = "duty", "Official duty"
    CLOSURE = "closure", "School closure"


class Decision(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


def weekdays_default():
    return [0, 1, 2, 3, 4]


class AttendancePolicy(TimestampedModel):
    academic_year = models.ForeignKey("academics.AcademicYear", on_delete=models.PROTECT)
    effective_from = models.DateField()
    working_weekdays = models.JSONField(default=weekdays_default)
    late_after = models.TimeField(default=time(8, 0))
    cutoff_time = models.TimeField(default=time(17, 0))
    late_credit = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=Decimal("1.00"),
        validators=[MinValueValidator(0), MaxValueValidator(1)],
    )
    exclude_excused = models.BooleanField(default=True)
    correction_window_days = models.PositiveSmallIntegerField(
        default=7, validators=[MaxValueValidator(365)]
    )
    low_attendance_threshold = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("75"),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    enforce_terms = models.BooleanField(default=True)

    class Meta:
        ordering = ["-effective_from", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["academic_year", "effective_from"], name="attendance_policy_date_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(late_credit__gte=0, late_credit__lte=1),
                name="attendance_late_credit_range",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    low_attendance_threshold__gte=0, low_attendance_threshold__lte=100
                ),
                name="attendance_threshold_range",
            ),
            models.CheckConstraint(
                condition=models.Q(cutoff_time__gt=models.F("late_after")),
                name="attendance_cutoff_after_late",
            ),
        ]
        permissions = [("manage_policy", "Can configure attendance policies and calendar")]

    def clean(self):
        super().clean()
        days = self.working_weekdays
        if (
            not isinstance(days, list)
            or not days
            or any(type(day) is not int or not 0 <= day <= 6 for day in days)
            or len(days) != len(set(days))
        ):
            raise ValidationError(
                {"working_weekdays": "Select distinct weekdays from Monday through Sunday."}
            )
        if (
            self.academic_year_id
            and self.effective_from
            and not self.academic_year.starts_on
            <= self.effective_from
            <= self.academic_year.ends_on
        ):
            raise ValidationError(
                {"effective_from": "The policy must start inside its academic year."}
            )

    def __str__(self):
        return f"{self.academic_year} · from {self.effective_from}"


class CalendarEvent(TimestampedModel):
    is_cancelled = models.BooleanField(default=False)
    cancellation_reason = models.CharField(max_length=500, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="attendance_calendar_cancellations",
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    academic_year = models.ForeignKey("academics.AcademicYear", on_delete=models.PROTECT)
    title = models.CharField(max_length=120)
    kind = models.CharField(
        max_length=16,
        choices=[
            ("public", "Public holiday"),
            ("school", "School holiday"),
            ("closure", "Unexpected closure"),
            ("working", "Additional working day"),
        ],
    )
    applies_to = models.CharField(
        max_length=10,
        choices=[("both", "Students and staff"), ("students", "Students"), ("staff", "Staff")],
        default="both",
    )
    starts_on = models.DateField()
    ends_on = models.DateField()
    reason = models.CharField(max_length=500)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        ordering = ["-starts_on", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_on__gte=models.F("starts_on")),
                name="attendance_calendar_dates",
            ),
            models.UniqueConstraint(
                fields=["academic_year", "title", "starts_on", "ends_on", "applies_to"],
                name="attendance_calendar_event_unique",
            ),
        ]

    def clean(self):
        super().clean()
        if (
            self.academic_year_id
            and self.starts_on
            and self.ends_on
            and not self.academic_year.starts_on
            <= self.starts_on
            <= self.ends_on
            <= self.academic_year.ends_on
        ):
            raise ValidationError("Calendar dates must fall inside the academic year.")

    def __str__(self):
        return self.title


class RegisterBase(TimestampedModel):
    academic_year = models.ForeignKey("academics.AcademicYear", on_delete=models.PROTECT)
    policy = models.ForeignKey(AttendancePolicy, on_delete=models.PROTECT)
    attendance_on = models.DateField()
    state = models.CharField(
        max_length=8, choices=[("draft", "Draft"), ("final", "Finalized")], default="draft"
    )
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="%(class)s_created"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="%(class)s_updated"
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="%(class)s_submitted",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    submission_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        abstract = True
        ordering = ["-attendance_on", "-pk"]


class StudentRegister(RegisterBase):
    section = models.ForeignKey("academics.Section", on_delete=models.PROTECT)

    class Meta(RegisterBase.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["academic_year", "section", "attendance_on"],
                name="unique_daily_class_register",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(state="draft", submitted_at__isnull=True, submitted_by__isnull=True)
                    | models.Q(
                        state="final", submitted_at__isnull=False, submitted_by__isnull=False
                    )
                ),
                name="student_register_submission_state",
            ),
        ]
        permissions = [
            ("view_attendance", "Can view scoped student attendance"),
            ("mark_attendance", "Can mark assigned student attendance"),
            ("view_all_attendance", "Can oversee all student attendance"),
            ("request_correction", "Can request student attendance corrections"),
            ("approve_correction", "Can approve student attendance corrections"),
            ("override_correction_window", "Can correct attendance outside its normal window"),
        ]

    def __str__(self):
        return f"{self.section} · {self.attendance_on}"


class StudentAttendance(TimestampedModel):
    register = models.ForeignKey(StudentRegister, on_delete=models.PROTECT, related_name="entries")
    enrollment = models.ForeignKey(
        "people.Enrollment", on_delete=models.PROTECT, related_name="attendance_entries"
    )
    student = models.ForeignKey("people.Student", on_delete=models.PROTECT)
    attendance_on = models.DateField()
    status = models.CharField(max_length=10, choices=StudentStatus.choices, blank=True)
    arrival_time = models.TimeField(null=True, blank=True)
    notes = models.CharField(max_length=500, blank=True)
    revision = models.PositiveIntegerField(default=0)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        ordering = ["-attendance_on", "student__first_name", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "attendance_on"], name="student_attendance_day_unique"
            ),
            models.UniqueConstraint(
                fields=["register", "enrollment"], name="student_register_enrollment_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["", *StudentStatus.values]),
                name="student_attendance_valid_status",
            ),
        ]
        indexes = [models.Index(fields=["attendance_on", "status"])]


class StaffRegister(RegisterBase):
    class Meta(RegisterBase.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["academic_year", "attendance_on"], name="unique_daily_staff_register"
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(state="draft", submitted_at__isnull=True, submitted_by__isnull=True)
                    | models.Q(
                        state="final", submitted_at__isnull=False, submitted_by__isnull=False
                    )
                ),
                name="staff_register_submission_state",
            ),
        ]
        permissions = [
            ("view_staff_attendance", "Can view own staff attendance"),
            ("view_all_staff_attendance", "Can view all staff attendance"),
            ("manage_staff_attendance", "Can maintain staff registers"),
            ("request_staff_correction", "Can request own staff attendance corrections"),
            ("approve_staff_correction", "Can approve staff attendance corrections"),
            ("request_leave", "Can submit own leave requests"),
            ("approve_leave", "Can decide leave requests"),
        ]

    def __str__(self):
        return f"Staff · {self.attendance_on}"


PERSON_CHECK = models.Q(teacher__isnull=False, staff__isnull=True) | models.Q(
    teacher__isnull=True, staff__isnull=False
)


class StaffAttendance(TimestampedModel):
    register = models.ForeignKey(StaffRegister, on_delete=models.PROTECT, related_name="entries")
    teacher = models.ForeignKey("people.Teacher", on_delete=models.PROTECT, null=True, blank=True)
    staff = models.ForeignKey("people.Staff", on_delete=models.PROTECT, null=True, blank=True)
    attendance_on = models.DateField()
    status = models.CharField(max_length=10, choices=StaffStatus.choices, blank=True)
    arrival_time = models.TimeField(null=True, blank=True)
    notes = models.CharField(max_length=500, blank=True)
    revision = models.PositiveIntegerField(default=0)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        ordering = ["-attendance_on", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=PERSON_CHECK, name="staff_attendance_exactly_one_person"
            ),
            models.UniqueConstraint(
                fields=["teacher", "attendance_on"],
                condition=models.Q(teacher__isnull=False),
                name="teacher_attendance_day_unique",
            ),
            models.UniqueConstraint(
                fields=["staff", "attendance_on"],
                condition=models.Q(staff__isnull=False),
                name="staff_attendance_day_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["", *StaffStatus.values]),
                name="staff_attendance_valid_status",
            ),
        ]
        indexes = [models.Index(fields=["attendance_on", "status"])]

    @property
    def person(self):
        return self.teacher if self.teacher_id else self.staff

    @property
    def person_key(self):
        return f"teacher:{self.teacher_id}" if self.teacher_id else f"staff:{self.staff_id}"


class AttendanceCorrection(TimestampedModel):
    student_entry = models.ForeignKey(
        StudentAttendance,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="corrections",
    )
    staff_entry = models.ForeignKey(
        StaffAttendance, on_delete=models.PROTECT, null=True, blank=True, related_name="corrections"
    )
    before = models.JSONField()
    after = models.JSONField()
    reason = models.CharField(max_length=500)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="attendance_corrections_requested",
    )
    state = models.CharField(max_length=10, choices=Decision.choices, default=Decision.PENDING)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="attendance_corrections_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    decision_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(student_entry__isnull=False, staff_entry__isnull=True)
                | models.Q(student_entry__isnull=True, staff_entry__isnull=False),
                name="correction_exactly_one_entry",
            ),
            models.UniqueConstraint(
                fields=["student_entry"],
                condition=models.Q(state="pending", student_entry__isnull=False),
                name="one_pending_student_correction",
            ),
            models.UniqueConstraint(
                fields=["staff_entry"],
                condition=models.Q(state="pending", staff_entry__isnull=False),
                name="one_pending_staff_correction",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(state="pending", reviewed_by__isnull=True, reviewed_at__isnull=True)
                    | models.Q(
                        state__in=["approved", "rejected"],
                        reviewed_by__isnull=False,
                        reviewed_at__isnull=False,
                    )
                ),
                name="attendance_correction_decision_fields",
            ),
            models.CheckConstraint(
                condition=~models.Q(requested_by=models.F("reviewed_by")),
                name="attendance_correction_no_self_approval",
            ),
            models.CheckConstraint(
                condition=~models.Q(reason=""), name="attendance_correction_reason_required"
            ),
        ]

    @property
    def entry(self):
        return self.student_entry if self.student_entry_id else self.staff_entry


class LeaveRequest(TimestampedModel):
    academic_year = models.ForeignKey("academics.AcademicYear", on_delete=models.PROTECT)
    teacher = models.ForeignKey("people.Teacher", on_delete=models.PROTECT, null=True, blank=True)
    staff = models.ForeignKey("people.Staff", on_delete=models.PROTECT, null=True, blank=True)
    starts_on = models.DateField()
    ends_on = models.DateField()
    kind = models.CharField(
        max_length=10,
        choices=[("sick", "Sick leave"), ("casual", "Casual leave"), ("annual", "Annual leave")],
    )
    reason = models.CharField(max_length=500)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="leave_requests"
    )
    state = models.CharField(max_length=10, choices=Decision.choices, default=Decision.PENDING)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="leave_decisions",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    decision_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-starts_on", "-pk"]
        constraints = [
            models.CheckConstraint(condition=PERSON_CHECK, name="leave_exactly_one_person"),
            models.CheckConstraint(
                condition=models.Q(ends_on__gte=models.F("starts_on")), name="leave_date_order"
            ),
            models.CheckConstraint(condition=~models.Q(reason=""), name="leave_reason_required"),
            models.CheckConstraint(
                condition=(
                    models.Q(state="pending", reviewed_by__isnull=True, reviewed_at__isnull=True)
                    | models.Q(
                        state__in=["approved", "rejected"],
                        reviewed_by__isnull=False,
                        reviewed_at__isnull=False,
                    )
                ),
                name="leave_decision_fields",
            ),
            models.CheckConstraint(
                condition=~models.Q(requested_by=models.F("reviewed_by")),
                name="leave_no_self_approval",
            ),
            *[
                ExclusionConstraint(
                    name=f"{field}_leave_no_overlap",
                    expressions=[
                        (field, "="),
                        (
                            models.Func(
                                "starts_on",
                                "ends_on",
                                models.Value("[]"),
                                function="DATERANGE",
                                output_field=DateRangeField(),
                            ),
                            "&&",
                        ),
                    ],
                    condition=models.Q(
                        **{f"{field}__isnull": False}, state__in=["pending", "approved"]
                    ),
                )
                for field in ("teacher", "staff")
            ],
        ]

    @property
    def person(self):
        return self.teacher if self.teacher_id else self.staff


class AbsenceNotification(TimestampedModel):
    entry = models.ForeignKey(
        StudentAttendance, on_delete=models.PROTECT, related_name="notifications"
    )
    guardian = models.ForeignKey("people.Guardian", on_delete=models.PROTECT)
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    revision = models.PositiveIntegerField()
    state = models.CharField(
        max_length=12,
        choices=[("active", "Active"), ("superseded", "Superseded")],
        default="active",
    )
    superseded_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["entry", "guardian", "revision"],
                name="unique_absence_notification_revision",
            ),
            models.UniqueConstraint(
                fields=["entry", "guardian"],
                condition=models.Q(state="active"),
                name="one_active_absence_notice",
            ),
        ]
