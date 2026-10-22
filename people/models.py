import uuid

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateRangeField
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from core.models import TimestampedModel


class NamedProfile(TimestampedModel):
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)

    class Meta:
        abstract = True

    def __str__(self):
        return f"{self.first_name} {self.last_name}".strip()


class Student(NamedProfile):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="student_profile",
    )
    admission_number = models.CharField(max_length=32, unique=True)
    is_active = models.BooleanField(default=True)
    admission_date = models.DateField(default=timezone.localdate)
    date_of_birth = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        default="enrolled",
        choices=[
            ("enrolled", "Enrolled"),
            ("withdrawn", "Withdrawn"),
            ("transferred", "Transferred out"),
            ("graduated", "Graduated"),
        ],
    )
    photo = models.FileField(upload_to="private/images/", blank=True)
    external_reference = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["first_name", "last_name", "admission_number"]
        permissions = [("view_all_students", "Can view all student records")]
        constraints = [
            models.UniqueConstraint(Lower("admission_number"), name="admission_number_case_unique"),
            models.CheckConstraint(
                condition=~models.Q(admission_number=""), name="admission_not_blank"
            ),
            models.UniqueConstraint(
                Lower("external_reference"),
                condition=~models.Q(external_reference=""),
                name="student_external_reference_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(date_of_birth__isnull=True)
                | models.Q(date_of_birth__lt=models.F("admission_date")),
                name="student_birth_before_admission",
            ),
        ]


class Guardian(NamedProfile):
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True, max_length=500)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="guardian_profile",
    )
    students = models.ManyToManyField(Student, through="GuardianStudent", related_name="guardians")


class GuardianStudent(TimestampedModel):
    guardian = models.ForeignKey(Guardian, on_delete=models.PROTECT, related_name="student_links")
    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name="guardian_links")
    relationship = models.CharField(max_length=48)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["guardian", "student"], name="unique_guardian_student")
        ]


class Teacher(NamedProfile):
    department = models.CharField(max_length=80, default="Teaching")
    left_on = models.DateField(null=True, blank=True)
    photo = models.FileField(upload_to="private/images/", blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    qualification = models.CharField(max_length=160, blank=True)
    joined_on = models.DateField(default=timezone.localdate)
    is_active = models.BooleanField(default=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="teacher_profile",
    )
    employee_number = models.CharField(max_length=32, unique=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(left_on__isnull=True)
                | models.Q(left_on__gte=models.F("joined_on")),
                name="teacher_employment_dates",
            )
        ]


class Staff(NamedProfile):
    department = models.CharField(max_length=80, default="Administration")
    left_on = models.DateField(null=True, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    joined_on = models.DateField(default=timezone.localdate)
    is_active = models.BooleanField(default=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="staff_profile",
    )
    employee_number = models.CharField(max_length=32, unique=True)
    job_title = models.CharField(max_length=100)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(left_on__isnull=True)
                | models.Q(left_on__gte=models.F("joined_on")),
                name="staff_employment_dates",
            )
        ]


class Enrollment(TimestampedModel):
    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name="enrollments")
    academic_year = models.ForeignKey(
        "academics.AcademicYear", on_delete=models.PROTECT, related_name="enrollments"
    )
    section = models.ForeignKey(
        "academics.Section", on_delete=models.PROTECT, related_name="enrollments"
    )
    started_on = models.DateField()
    ended_on = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    roll_number = models.CharField(max_length=24, blank=True)
    exit_reason = models.CharField(
        max_length=16,
        blank=True,
        choices=[
            ("transfer", "Section transfer"),
            ("promote", "Promoted"),
            ("withdraw", "Withdrawn"),
            ("graduate", "Graduated"),
            ("transfer_out", "Transferred out"),
        ],
    )
    notes = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-academic_year__starts_on", "-started_on", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["student"],
                condition=models.Q(is_active=True),
                name="one_active_enrollment_per_student",
            ),
            ExclusionConstraint(
                name="student_placements_do_not_overlap",
                expressions=[
                    ("student", "="),
                    (
                        models.Func(
                            "started_on",
                            "ended_on",
                            models.Value("[]"),
                            function="DATERANGE",
                            output_field=DateRangeField(),
                        ),
                        "&&",
                    ),
                ],
            ),
            models.UniqueConstraint(
                fields=["academic_year", "section", "roll_number"],
                condition=models.Q(is_active=True) & ~models.Q(roll_number=""),
                name="unique_active_section_roll",
            ),
            models.UniqueConstraint(
                fields=["student", "academic_year"],
                condition=models.Q(is_active=True),
                name="one_active_enrollment_per_year",
            ),
            models.CheckConstraint(
                condition=models.Q(ended_on__isnull=True)
                | models.Q(ended_on__gte=models.F("started_on")),
                name="enrollment_date_order",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(is_active=True, ended_on__isnull=True)
                    | models.Q(is_active=False, ended_on__isnull=False)
                ),
                name="enrollment_active_matches_end",
            ),
        ]
        indexes = [models.Index(fields=["academic_year", "section", "is_active"])]

    def clean(self):
        super().clean()
        if not (self.academic_year_id and self.started_on):
            return
        year = self.academic_year
        if not year.starts_on <= self.started_on <= year.ends_on:
            raise ValidationError({"started_on": "Start date must fall within the academic year."})
        if self.ended_on and not self.started_on <= self.ended_on <= year.ends_on:
            raise ValidationError({"ended_on": "End date must fall within the placement and year."})
        if self.student_id:
            overlapping = (
                Enrollment.objects.filter(
                    student_id=self.student_id,
                    academic_year_id=self.academic_year_id,
                    started_on__lte=self.ended_on or year.ends_on,
                )
                .exclude(pk=self.pk)
                .filter(models.Q(ended_on__isnull=True) | models.Q(ended_on__gte=self.started_on))
            )
            if overlapping.exists():
                raise ValidationError("Enrollment dates cannot overlap an existing placement.")


class AdmissionCounter(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    next_number = models.PositiveBigIntegerField(default=1)


class AdmissionImport(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    rows = models.JSONField(default=list)
    expires_at = models.DateTimeField()
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        permissions = [
            ("import_students", "Can import student admissions"),
            ("transition_students", "Can transfer, promote or withdraw students"),
        ]
