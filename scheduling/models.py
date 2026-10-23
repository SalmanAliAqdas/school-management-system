from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField
from django.db import models

from core.models import TimestampedModel


class Room(TimestampedModel):
    name = models.CharField(max_length=80, unique=True)
    kind = models.CharField(
        max_length=20,
        choices=[("classroom", "Classroom"), ("lab", "Laboratory"), ("other", "Other")],
        default="classroom",
    )
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Period(TimestampedModel):
    academic_year = models.ForeignKey("academics.AcademicYear", on_delete=models.PROTECT)
    shift = models.CharField(max_length=40, default="Day")
    name = models.CharField(max_length=60)
    weekday = models.PositiveSmallIntegerField(
        choices=list(
            enumerate(
                ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            )
        )
    )
    starts_at = models.TimeField()
    ends_at = models.TimeField()
    kind = models.CharField(
        max_length=12,
        choices=[
            ("lesson", "Lesson"),
            ("break", "Break"),
            ("lunch", "Lunch"),
            ("assembly", "Assembly"),
        ],
        default="lesson",
    )

    class Meta:
        ordering = ["weekday", "starts_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")), name="period_order"
            ),
            models.CheckConstraint(condition=models.Q(weekday__lte=6), name="period_weekday"),
        ]

    def __str__(self):
        return f"{self.get_weekday_display()} {self.starts_at:%H:%M} {self.name} ({self.shift})"


class Timetable(TimestampedModel):
    title = models.CharField(max_length=100)
    academic_year = models.ForeignKey("academics.AcademicYear", on_delete=models.PROTECT)
    term = models.ForeignKey("academics.Term", on_delete=models.PROTECT, null=True, blank=True)
    starts_on = models.DateField()
    ends_on = models.DateField()
    state = models.CharField(
        max_length=12,
        choices=[("draft", "Draft"), ("published", "Published"), ("archived", "Archived")],
        default="draft",
    )
    revision = models.PositiveIntegerField(default=1)

    class Meta:
        permissions = [("manage_timetable", "Manage and publish timetable")]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_on__gte=models.F("starts_on")), name="timetable_dates"
            )
        ]

    def __str__(self):
        return self.title


class Entry(TimestampedModel):
    timetable = models.ForeignKey(Timetable, on_delete=models.PROTECT, related_name="entries")
    period = models.ForeignKey(Period, on_delete=models.PROTECT)
    assignment = models.ForeignKey("academics.TeachingAssignment", on_delete=models.PROTECT)
    room = models.ForeignKey(Room, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["timetable", "period", "assignment"], name="unique_timetable_entry"
            )
        ]


class Availability(TimestampedModel):
    teacher = models.ForeignKey("people.Teacher", on_delete=models.PROTECT)
    period = models.ForeignKey(Period, on_delete=models.PROTECT)
    kind = models.CharField(
        max_length=12,
        choices=[
            ("available", "Available"),
            ("unavailable", "Unavailable"),
            ("preferred", "Preferred"),
        ],
        default="unavailable",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["teacher", "period"], name="teacher_period_availability"
            )
        ]


class WorkloadLimit(TimestampedModel):
    teacher = models.OneToOneField("people.Teacher", on_delete=models.PROTECT)
    daily = models.PositiveSmallIntegerField(default=8)
    weekly = models.PositiveSmallIntegerField(default=35)


class Substitution(TimestampedModel):
    entry = models.ForeignKey(Entry, on_delete=models.PROTECT, related_name="substitutions")
    date = models.DateField()
    teacher = models.ForeignKey("people.Teacher", on_delete=models.PROTECT)
    reason = models.CharField(max_length=500)
    state = models.CharField(
        max_length=12,
        choices=[("pending", "Pending"), ("approved", "Approved"), ("cancelled", "Cancelled")],
        default="pending",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["entry", "date"],
                condition=models.Q(state__in=["pending", "approved"]),
                name="one_live_substitution",
            )
        ]


class ScheduleHistory(TimestampedModel):
    timetable = models.ForeignKey(Timetable, on_delete=models.PROTECT)
    actor = models.ForeignKey("accounts.User", on_delete=models.PROTECT)
    action = models.CharField(max_length=40)
    detail = models.JSONField(default=dict)


class Booking(TimestampedModel):
    """Materialized published occurrences; PostgreSQL prevents resource double booking."""

    entry = models.ForeignKey(Entry, on_delete=models.PROTECT, related_name="bookings")
    date = models.DateField()
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    teacher = models.ForeignKey("people.Teacher", on_delete=models.PROTECT)
    section = models.ForeignKey("academics.Section", on_delete=models.PROTECT)
    room = models.ForeignKey(Room, on_delete=models.PROTECT)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["entry", "date"], name="one_lesson_occurrence"),
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")), name="booking_times"
            ),
            *[
                ExclusionConstraint(
                    name=f"booking_{field}_no_overlap",
                    expressions=[
                        (field, "="),
                        (
                            models.Func(
                                "starts_at",
                                "ends_at",
                                models.Value("[)"),
                                function="TSTZRANGE",
                                output_field=DateTimeRangeField(),
                            ),
                            "&&",
                        ),
                    ],
                    condition=models.Q(active=True),
                )
                for field in ("teacher", "section", "room")
            ],
        ]


class AssignmentAccessEvent(TimestampedModel):
    assignment = models.ForeignKey("academics.TeachingAssignment", on_delete=models.PROTECT)
    actor = models.ForeignKey("accounts.User", on_delete=models.PROTECT)
    active = models.BooleanField()
    reason = models.CharField(max_length=500)
