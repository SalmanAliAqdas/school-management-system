import uuid
from decimal import Decimal

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, DecimalRangeField
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from core.models import TimestampedModel


def percent(default=Decimal("50")):
    return models.DecimalField(
        max_digits=6,
        decimal_places=3,
        default=default,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )


def bounds(field, *, positive=False, upper=100):
    return models.Q(**{f"{field}__gt" if positive else f"{field}__gte": 0, f"{field}__lte": upper})


class AssessmentType(TimestampedModel):
    name = models.CharField(max_length=80, unique=True)
    description = models.CharField(max_length=300, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ExaminationSettings(TimestampedModel):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    ranking_enabled = models.BooleanField(default=False)
    ranking_scope = models.CharField(
        max_length=12, default="section", choices=[("section", "Section"), ("class", "Class")]
    )
    ranking_ties = models.CharField(
        max_length=12,
        default="competition",
        choices=[("competition", "1, 2, 2, 4"), ("dense", "1, 2, 2, 3")],
    )
    ranking_pass_only = models.BooleanField(default=False)
    support_threshold = percent(Decimal("50"))

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(pk=1), name="exam_single_settings"),
            models.CheckConstraint(
                condition=bounds("support_threshold"), name="exam_support_range"
            ),
        ]


class GradingPolicy(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    academic_year = models.ForeignKey("academics.AcademicYear", on_delete=models.PROTECT)
    name = models.CharField(max_length=100)
    overall_pass = percent()
    require_subject_pass = models.BooleanField(default=True)
    absence_rule = models.CharField(
        max_length=12,
        default="incomplete",
        choices=[
            ("incomplete", "Incomplete; no percentage"),
            ("zero", "Explicit zero credit for absence"),
        ],
    )
    exemption_rule = models.CharField(
        max_length=12,
        default="exclude",
        choices=[("exclude", "Exclude exempt weight"), ("incomplete", "Require academic review")],
    )
    optional_rule = models.CharField(
        max_length=12,
        default="exclude",
        choices=[
            ("exclude", "Exclude pending optional assessments"),
            ("required", "All optional assessments required"),
        ],
    )
    decimal_places = models.PositiveSmallIntegerField(default=2, validators=[MaxValueValidator(3)])
    independent_review = models.BooleanField(default=True)
    principal_approval = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["academic_year", "name"], name="exam_policy_name"),
            models.CheckConstraint(
                condition=bounds("overall_pass"), name="exam_overall_pass_range"
            ),
            models.CheckConstraint(
                condition=models.Q(decimal_places__lte=3), name="exam_rounding_range"
            ),
        ]

    def __str__(self):
        return f"{self.academic_year} · {self.name}"


class GradeBand(TimestampedModel):
    policy = models.ForeignKey(GradingPolicy, on_delete=models.PROTECT, related_name="bands")
    lower = percent(Decimal("0"))
    upper = percent(Decimal("100"))
    label = models.CharField(max_length=12)
    description = models.CharField(max_length=180, blank=True)
    points = models.DecimalField(
        max_digits=6, decimal_places=3, null=True, blank=True, validators=[MinValueValidator(0)]
    )

    class Meta:
        ordering = ["lower"]
        constraints = [
            ExclusionConstraint(
                name="exam_grade_bands_no_overlap",
                expressions=[
                    ("policy", "="),
                    (
                        models.Func(
                            "lower",
                            "upper",
                            models.Value("[)"),
                            function="NUMRANGE",
                            output_field=DecimalRangeField(),
                        ),
                        "&&",
                    ),
                ],
            ),
            models.UniqueConstraint(fields=["policy", "lower"], name="exam_grade_lower_unique"),
            models.CheckConstraint(
                condition=bounds("lower") & bounds("upper") & models.Q(upper__gt=models.F("lower")),
                name="exam_grade_bounds",
            ),
            models.CheckConstraint(
                condition=models.Q(points__isnull=True) | models.Q(points__gte=0),
                name="exam_grade_points_nonnegative",
            ),
        ]


class ExamSession(TimestampedModel):
    class State(models.TextChoices):
        DRAFT = "draft", "Draft setup"
        OPEN = "open", "Marks entry open"
        CLOSED = "closed", "Marks entry closed"
        REVIEW = "review", "Under review"
        APPROVED = "approved", "Approved"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    academic_year = models.ForeignKey(
        "academics.AcademicYear", on_delete=models.PROTECT, related_name="exam_sessions"
    )
    term = models.ForeignKey("academics.Term", on_delete=models.PROTECT, null=True, blank=True)
    assessment_type = models.ForeignKey(AssessmentType, on_delete=models.PROTECT)
    policy = models.ForeignKey(GradingPolicy, on_delete=models.PROTECT, related_name="sessions")
    name = models.CharField(max_length=140)
    description = models.TextField(max_length=2000, blank=True)
    retake_of = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="retakes",
        help_text=(
            "Optional supplementary session. Only original candidates are eligible; "
            "source selection stays explicit."
        ),
    )
    starts_on = models.DateField()
    ends_on = models.DateField()
    eligibility_on = models.DateField(help_text="Enrollment roster date; retained after transfers.")
    report_kind = models.CharField(
        max_length=12,
        default="assessment",
        choices=[
            ("assessment", "Assessment session"),
            ("term", "Weighted term report"),
            ("annual", "Weighted annual report"),
        ],
    )
    state = models.CharField(max_length=12, choices=State.choices, default=State.DRAFT)
    version = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_exams"
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="approved_exams",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    controllers = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through="ExamController", related_name="controlled_exams"
    )

    class Meta:
        ordering = ["-starts_on", "name"]
        indexes = [models.Index(fields=["academic_year", "state"], name="exam_year_state_idx")]
        permissions = [
            ("view_examinations", "Can access examinations"),
            ("manage_examinations", "Can configure examinations and grading"),
            ("view_all_examinations", "Can oversee all examination records"),
            ("enter_marks", "Can enter assigned subject marks"),
            ("review_results", "Can review controlled examination results"),
            ("approve_results", "Can approve examination results"),
            ("publish_results", "Can publish examination results"),
            ("correct_results", "Can request mark corrections"),
            ("decide_corrections", "Can decide independent mark corrections"),
            ("override_promotion", "Can record promotion recommendation overrides"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["academic_year", "name"], name="exam_name_per_year"),
            models.CheckConstraint(
                condition=models.Q(ends_on__gte=models.F("starts_on"))
                & models.Q(eligibility_on__gte=models.F("starts_on"))
                & models.Q(eligibility_on__lte=models.F("ends_on")),
                name="exam_session_dates",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        approved_by__isnull=True,
                        approved_at__isnull=True,
                        state__in=["draft", "open", "closed", "review"],
                    )
                    | models.Q(
                        approved_by__isnull=False,
                        approved_at__isnull=False,
                        state__in=["approved", "published", "archived"],
                    )
                ),
                name="exam_approval_fields",
            ),
        ]

    def __str__(self):
        return self.name


class ExamController(TimestampedModel):
    session = models.ForeignKey(
        ExamSession, on_delete=models.PROTECT, related_name="controller_links"
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["session", "user"], name="exam_controller_unique")
        ]


class ExamCohort(TimestampedModel):
    session = models.ForeignKey(ExamSession, on_delete=models.PROTECT, related_name="cohorts")
    section = models.ForeignKey("academics.Section", on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["session", "section"], name="exam_cohort_unique")
        ]

    def __str__(self):
        return f"{self.session} · {self.section}"


class ExamSubject(TimestampedModel):
    cohort = models.ForeignKey(ExamCohort, on_delete=models.PROTECT, related_name="subjects")
    subject = models.ForeignKey("academics.Subject", on_delete=models.PROTECT)
    weight = percent(Decimal("100"))
    passing_percentage = percent()
    required = models.BooleanField(
        default=True, help_text="Required for promotion and subject-pass rules."
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["cohort", "subject"], name="exam_subject_unique"),
            models.CheckConstraint(
                condition=bounds("weight", positive=True) & bounds("passing_percentage"),
                name="exam_subject_weight_pass",
            ),
        ]

    def __str__(self):
        return f"{self.cohort.section} · {self.subject}"


class Assessment(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    exam_subject = models.ForeignKey(
        ExamSubject, on_delete=models.PROTECT, related_name="assessments"
    )
    assessment_type = models.ForeignKey(AssessmentType, on_delete=models.PROTECT)
    name = models.CharField(max_length=100)
    component = models.CharField(
        max_length=16,
        default="theory",
        choices=[
            ("theory", "Theory"),
            ("practical", "Practical"),
            ("oral", "Oral"),
            ("coursework", "Coursework"),
            ("other", "Other"),
        ],
    )
    max_marks = models.DecimalField(
        max_digits=9, decimal_places=3, validators=[MinValueValidator(Decimal("0.001"))]
    )
    weight = percent(Decimal("100"))
    passing_percentage = percent()
    require_pass = models.BooleanField(default=False)
    optional = models.BooleanField(default=False)

    class Meta:
        ordering = ["name", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["exam_subject", "name"], name="exam_assessment_unique"),
            models.CheckConstraint(
                condition=bounds("weight", positive=True)
                & bounds("passing_percentage")
                & models.Q(max_marks__gt=0),
                name="exam_assessment_ranges",
            ),
        ]

    def __str__(self):
        return f"{self.exam_subject} · {self.name}"


class SessionContribution(TimestampedModel):
    session = models.ForeignKey(ExamSession, on_delete=models.PROTECT, related_name="contributions")
    source = models.ForeignKey(ExamSession, on_delete=models.PROTECT, related_name="contributed_to")
    weight = percent(Decimal("100"))

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["session", "source"], name="exam_source_unique"),
            models.CheckConstraint(
                condition=bounds("weight", positive=True) & ~models.Q(session=models.F("source")),
                name="exam_source_weight",
            ),
        ]


class ExamRoom(TimestampedModel):
    name = models.CharField(max_length=80, unique=True)

    def __str__(self):
        return self.name


def time_overlap():
    return models.Func(
        "starts_at",
        "ends_at",
        models.Value("[)"),
        function="TSTZRANGE",
        output_field=DateTimeRangeField(),
    )


class ExamSchedule(TimestampedModel):
    assessment = models.OneToOneField(Assessment, on_delete=models.PROTECT, related_name="schedule")
    section = models.ForeignKey("academics.Section", on_delete=models.PROTECT)
    school_class = models.ForeignKey("academics.SchoolClass", on_delete=models.PROTECT)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    room = models.ForeignKey(ExamRoom, on_delete=models.PROTECT, null=True, blank=True)
    invigilators = models.ManyToManyField("people.Teacher", through="Invigilation")

    class Meta:
        ordering = ["starts_at", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")), name="exam_slot_time_order"
            ),
            ExclusionConstraint(
                name="exam_section_slot_no_overlap",
                expressions=[("section", "="), (time_overlap(), "&&")],
            ),
            ExclusionConstraint(
                name="exam_class_slot_no_overlap",
                expressions=[("school_class", "="), (time_overlap(), "&&")],
            ),
            ExclusionConstraint(
                name="exam_room_slot_no_overlap",
                expressions=[("room", "="), (time_overlap(), "&&")],
                condition=models.Q(room__isnull=False),
            ),
        ]


class Invigilation(TimestampedModel):
    schedule = models.ForeignKey(ExamSchedule, on_delete=models.PROTECT, related_name="duties")
    teacher = models.ForeignKey("people.Teacher", on_delete=models.PROTECT)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["schedule", "teacher"], name="exam_invigilator_unique"),
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")), name="exam_duty_time_order"
            ),
            ExclusionConstraint(
                name="exam_invigilator_slot_no_overlap",
                expressions=[("teacher", "="), (time_overlap(), "&&")],
            ),
        ]


class ExamCandidate(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cohort = models.ForeignKey(ExamCohort, on_delete=models.PROTECT, related_name="candidates")
    session = models.ForeignKey(ExamSession, on_delete=models.PROTECT, related_name="candidates")
    student = models.ForeignKey("people.Student", on_delete=models.PROTECT)
    enrollment = models.ForeignKey(
        "people.Enrollment", on_delete=models.PROTECT, related_name="exam_candidates"
    )
    withheld = models.BooleanField(default=False)
    withholding_reason = models.CharField(max_length=500, blank=True)
    teacher_remarks = models.CharField(max_length=1000, blank=True)
    principal_remarks = models.CharField(max_length=1000, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["session", "student"], name="exam_candidate_unique"),
            models.CheckConstraint(
                condition=models.Q(withheld=False, withholding_reason="")
                | (models.Q(withheld=True) & ~models.Q(withholding_reason="")),
                name="exam_withhold_reason",
            ),
        ]

    def __str__(self):
        return f"{self.student} · {self.session}"


class MarkSheet(TimestampedModel):
    assessment = models.OneToOneField(Assessment, on_delete=models.PROTECT, related_name="sheet")
    state = models.CharField(
        max_length=12,
        default="draft",
        choices=[
            ("draft", "Draft"),
            ("submitted", "Submitted"),
            ("review", "Under review"),
            ("returned", "Returned for correction"),
            ("approved", "Controller approved"),
        ],
    )
    version = models.PositiveIntegerField(default=0)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="submitted_mark_sheets",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviewed_mark_sheets",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_reason = models.CharField(max_length=1000, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    state__in=["draft", "submitted", "review", "returned", "approved"]
                ),
                name="exam_sheet_valid_state",
            )
        ]


class MarkEntry(TimestampedModel):
    class Status(models.TextChoices):
        ASSESSED = "assessed", "Present and assessed"
        ABSENT = "absent", "Absent"
        EXEMPT = "exempt", "Exempt"
        INCOMPLETE = "incomplete", "Incomplete"
        PENDING = "pending", "Pending assessment"
        WITHHELD = "withheld", "Withheld"

    sheet = models.ForeignKey(MarkSheet, on_delete=models.PROTECT, related_name="entries")
    candidate = models.ForeignKey(ExamCandidate, on_delete=models.PROTECT, related_name="marks")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    marks = models.DecimalField(max_digits=9, decimal_places=3, null=True, blank=True)
    remarks = models.CharField(max_length=500, blank=True)
    version = models.PositiveIntegerField(default=0)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["sheet", "candidate"], name="exam_mark_unique"),
            models.CheckConstraint(
                condition=(
                    models.Q(status="assessed", marks__isnull=False, marks__gte=0)
                    | models.Q(
                        status__in=["absent", "exempt", "incomplete", "pending", "withheld"],
                        marks__isnull=True,
                    )
                ),
                name="exam_mark_status_value",
            ),
        ]


class ResultPublication(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(ExamSession, on_delete=models.PROTECT, related_name="publications")
    version = models.PositiveIntegerField()
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reason = models.CharField(max_length=1000)
    ranking_policy = models.JSONField(default=dict)

    class Meta:
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(fields=["session", "version"], name="exam_publication_version")
        ]


class PublishedResult(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    publication = models.ForeignKey(
        ResultPublication, on_delete=models.PROTECT, related_name="results"
    )
    candidate = models.ForeignKey(ExamCandidate, on_delete=models.PROTECT, related_name="results")
    data = models.JSONField()

    class Meta:
        indexes = [models.Index(fields=["candidate", "publication"], name="exam_candidate_pub_idx")]
        constraints = [
            models.UniqueConstraint(
                fields=["publication", "candidate"], name="exam_snapshot_unique"
            )
        ]


class ResultCorrection(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entry = models.ForeignKey(MarkEntry, on_delete=models.PROTECT, related_name="corrections")
    before = models.JSONField()
    after = models.JSONField()
    reason = models.CharField(max_length=1000)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="requested_result_corrections",
    )
    state = models.CharField(
        max_length=12,
        default="pending",
        choices=[
            ("pending", "Awaiting review"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="decided_result_corrections",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    decision_reason = models.CharField(max_length=1000, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["entry"],
                condition=models.Q(state="pending"),
                name="exam_one_pending_correction",
            ),
            models.CheckConstraint(condition=~models.Q(reason=""), name="exam_correction_reason"),
            models.CheckConstraint(
                condition=(
                    models.Q(state="pending", reviewed_by__isnull=True, reviewed_at__isnull=True)
                    | (
                        models.Q(
                            state__in=["approved", "rejected"],
                            reviewed_by__isnull=False,
                            reviewed_at__isnull=False,
                        )
                        & ~models.Q(requested_by=models.F("reviewed_by"))
                        & ~models.Q(decision_reason="")
                    )
                ),
                name="exam_correction_decision",
            ),
        ]


class ResultEvent(TimestampedModel):
    session = models.ForeignKey(ExamSession, on_delete=models.PROTECT, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    action = models.CharField(max_length=40)
    reason = models.CharField(max_length=1000)
    sheet = models.ForeignKey(MarkSheet, on_delete=models.PROTECT, null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    @property
    def label(self):
        return {
            "publish": "Results published",
            "review": "Results awaiting final approval",
            "approve": "Results approved",
            "open": "Marks entry opened",
            "close": "Marks entry closed",
            "reopen": "Marks entry reopened",
            "sheet_return": "Submission returned",
            "sheet_approve": "Marks sheet approved",
            "sheet_review": "Marks review started",
        }.get(self.action, self.action.replace("_", " ").capitalize())


class ExamNotification(TimestampedModel):
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    event = models.ForeignKey(ResultEvent, on_delete=models.PROTECT, related_name="notifications")
    candidate = models.ForeignKey(ExamCandidate, on_delete=models.PROTECT, null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["recipient", "-created_at"], name="exam_recipient_date_idx")
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "event", "candidate"],
                nulls_distinct=False,
                name="exam_notice_unique",
            )
        ]


class PromotionRecommendation(TimestampedModel):
    candidate = models.ForeignKey(
        ExamCandidate, on_delete=models.PROTECT, related_name="recommendation_overrides"
    )
    publication = models.ForeignKey(ResultPublication, on_delete=models.PROTECT)
    eligible = models.BooleanField()
    reason = models.CharField(max_length=1000)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=~models.Q(reason=""), name="exam_override_reason")
        ]


class CandidateAmendment(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    candidate = models.ForeignKey(
        ExamCandidate, on_delete=models.PROTECT, related_name="amendments"
    )
    before = models.JSONField()
    after = models.JSONField()
    reason = models.CharField(max_length=1000)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="requested_result_amendments",
    )
    state = models.CharField(
        max_length=12,
        default="pending",
        choices=[
            ("pending", "Awaiting review"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="decided_result_amendments",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    decision_reason = models.CharField(max_length=1000, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["candidate"],
                condition=models.Q(state="pending"),
                name="exam_one_pending_amendment",
            ),
            models.CheckConstraint(condition=~models.Q(reason=""), name="exam_amendment_reason"),
            models.CheckConstraint(
                condition=models.Q(
                    state="pending", reviewed_by__isnull=True, reviewed_at__isnull=True
                )
                | (
                    models.Q(
                        state__in=["approved", "rejected"],
                        reviewed_by__isnull=False,
                        reviewed_at__isnull=False,
                    )
                    & ~models.Q(requested_by=models.F("reviewed_by"))
                    & ~models.Q(decision_reason="")
                ),
                name="exam_amendment_decision",
            ),
        ]
