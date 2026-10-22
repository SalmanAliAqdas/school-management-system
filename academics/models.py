from django.core.exceptions import ValidationError
from django.db import models

from core.models import TimestampedModel


class AcademicYear(TimestampedModel):
    name = models.CharField(max_length=32, unique=True)
    starts_on = models.DateField()
    ends_on = models.DateField()
    is_current = models.BooleanField(default=False)

    class Meta:
        ordering = ["-starts_on"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_on__gt=models.F("starts_on")), name="year_date_order"
            ),
            models.UniqueConstraint(
                fields=["is_current"], condition=models.Q(is_current=True), name="one_current_year"
            ),
        ]

    def __str__(self):
        return self.name


class Term(TimestampedModel):
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT, related_name="terms")
    name = models.CharField(max_length=64)
    starts_on = models.DateField()
    ends_on = models.DateField()

    class Meta:
        ordering = ["starts_on"]
        constraints = [
            models.UniqueConstraint(fields=["academic_year", "name"], name="term_name_per_year"),
            models.CheckConstraint(
                condition=models.Q(ends_on__gte=models.F("starts_on")), name="term_date_order"
            ),
        ]

    def clean(self):
        super().clean()
        if self.academic_year_id and self.starts_on and self.ends_on:
            year = self.academic_year
            if self.starts_on < year.starts_on or self.ends_on > year.ends_on:
                raise ValidationError("Term dates must fall within the academic year.")

    def __str__(self):
        return f"{self.academic_year} · {self.name}"


class SchoolClass(TimestampedModel):
    name = models.CharField(max_length=64, unique=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name_plural = "Classes"

    def __str__(self):
        return self.name


class Section(TimestampedModel):
    school_class = models.ForeignKey(SchoolClass, on_delete=models.PROTECT, related_name="sections")
    name = models.CharField(max_length=32)

    class Meta:
        ordering = ["school_class__sort_order", "name"]
        constraints = [
            models.UniqueConstraint(fields=["school_class", "name"], name="section_per_class")
        ]

    def __str__(self):
        return f"{self.school_class} · {self.name}"


class Subject(TimestampedModel):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name


class TeachingAssignment(TimestampedModel):
    teacher = models.ForeignKey(
        "people.Teacher", on_delete=models.PROTECT, related_name="assignments"
    )
    academic_year = models.ForeignKey(
        AcademicYear, on_delete=models.PROTECT, related_name="teaching_assignments"
    )
    section = models.ForeignKey(
        Section, on_delete=models.PROTECT, related_name="teaching_assignments"
    )
    subject = models.ForeignKey(
        Subject, on_delete=models.PROTECT, related_name="teaching_assignments"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["teacher", "academic_year", "section", "subject"],
                name="unique_teaching_assignment",
            )
        ]
        indexes = [models.Index(fields=["academic_year", "section"])]

    def __str__(self):
        return f"{self.teacher} · {self.section} · {self.subject}"
