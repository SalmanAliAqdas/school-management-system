from django.db import models

from core.models import TimestampedModel


class Assignment(TimestampedModel):
    teaching = models.ForeignKey("academics.TeachingAssignment", on_delete=models.PROTECT)
    title = models.CharField(max_length=160)
    description = models.TextField(max_length=12000)
    kind = models.CharField(
        max_length=20,
        choices=[
            (x, x.title())
            for x in [
                "homework",
                "classwork",
                "project",
                "essay",
                "worksheet",
                "practical",
                "reading",
                "other",
            ]
        ],
        default="homework",
    )
    publish_at = models.DateTimeField()
    due_at = models.DateTimeField()
    maximum = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    rubric = models.JSONField(
        default=dict,
        blank=True,
        help_text="Optional criterion names mapped to positive maximum marks.",
    )
    late_allowed = models.BooleanField(default=False)
    late_penalty = models.DecimalField(
        max_digits=5, decimal_places=2, default=0, help_text="Percentage deduction for late work."
    )
    submission_required = models.BooleanField(default=True)
    state = models.CharField(
        max_length=12,
        choices=[
            ("draft", "Draft"),
            ("scheduled", "Scheduled / published"),
            ("closed", "Closed"),
            ("archived", "Archived"),
        ],
        default="draft",
    )
    revision = models.PositiveIntegerField(default=1)

    class Meta:
        permissions = [("manage_learning", "Oversee learning assignments")]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(due_at__gt=models.F("publish_at")), name="assignment_dates"
            ),
            models.CheckConstraint(
                condition=models.Q(maximum__isnull=True) | models.Q(maximum__gt=0),
                name="assignment_maximum",
            ),
            models.CheckConstraint(
                condition=models.Q(late_penalty__gte=0, late_penalty__lte=100),
                name="assignment_penalty",
            ),
        ]

    def __str__(self):
        return self.title


class AssignmentChange(TimestampedModel):
    assignment = models.ForeignKey(Assignment, on_delete=models.PROTECT, related_name="changes")
    actor = models.ForeignKey("accounts.User", on_delete=models.PROTECT)
    action = models.CharField(max_length=30)
    snapshot = models.JSONField(default=dict)


class Submission(TimestampedModel):
    assignment = models.ForeignKey(Assignment, on_delete=models.PROTECT, related_name="submissions")
    student = models.ForeignKey("people.Student", on_delete=models.PROTECT)
    state = models.CharField(
        max_length=12,
        choices=[
            (x, x.title())
            for x in ["draft", "submitted", "returned", "reviewed", "graded", "excused"]
        ],
        default="draft",
    )
    revision = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["assignment", "student"], name="one_assignment_submission"
            )
        ]


class SubmissionVersion(TimestampedModel):
    submission = models.ForeignKey(Submission, on_delete=models.PROTECT, related_name="versions")
    number = models.PositiveIntegerField()
    text = models.TextField(max_length=20000, blank=True)
    final = models.BooleanField(default=False)
    late = models.BooleanField(default=False)

    class Meta:
        ordering = ["-number"]
        constraints = [
            models.UniqueConstraint(
                fields=["submission", "number"], name="submission_version_number"
            )
        ]


class Feedback(TimestampedModel):
    submission = models.ForeignKey(Submission, on_delete=models.PROTECT, related_name="feedback")
    version = models.ForeignKey(SubmissionVersion, on_delete=models.PROTECT, null=True, blank=True)
    actor = models.ForeignKey("accounts.User", on_delete=models.PROTECT)
    text = models.TextField(max_length=10000)
    marks = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    criterion_marks = models.JSONField(default=dict, blank=True)
    outcome = models.CharField(
        max_length=12,
        choices=[(x, x.title()) for x in ["reviewed", "graded", "returned", "excused"]],
        default="reviewed",
    )
    released = models.BooleanField(default=False)
    guardian_visible = models.BooleanField(default=False)

    class Meta:
        ordering = ["-pk"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(marks__isnull=True) | models.Q(marks__gte=0),
                name="feedback_nonnegative",
            )
        ]


class Attachment(TimestampedModel):
    assignment = models.ForeignKey(Assignment, on_delete=models.PROTECT, related_name="attachments")
    version = models.ForeignKey(
        SubmissionVersion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="attachments",
    )
    filename = models.CharField(max_length=120)
    content_type = models.CharField(max_length=80)
    data = models.BinaryField()
