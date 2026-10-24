from django.conf import settings
from django.db import models

from core.models import TimestampedModel


class Department(TimestampedModel):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=20, unique=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Designation(TimestampedModel):
    department = models.ForeignKey(Department, on_delete=models.PROTECT)
    title = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["department", "title"], name="hr_unique_designation")
        ]


class Employee(TimestampedModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="hr_employee"
    )
    staff = models.OneToOneField("people.Staff", null=True, blank=True, on_delete=models.PROTECT)
    teacher = models.OneToOneField(
        "people.Teacher", null=True, blank=True, on_delete=models.PROTECT
    )
    employee_code = models.CharField(max_length=32, unique=True)
    emergency_contact = models.CharField(max_length=160, blank=True)
    status = models.CharField(
        max_length=20,
        default="active",
        choices=[
            (x, x.title()) for x in ["active", "probation", "notice", "resigned", "terminated"]
        ],
    )

    class Meta:
        permissions = [
            ("manage_hr", "Manage confidential HR records"),
            ("view_all_hr", "View all HR records"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(staff__isnull=False, teacher__isnull=True)
                    | models.Q(staff__isnull=True, teacher__isnull=False)
                ),
                name="hr_one_identity",
            )
        ]

    @property
    def name(self):
        return str(self.staff or self.teacher)


class EmploymentRecord(TimestampedModel):
    employee = models.ForeignKey(
        Employee, on_delete=models.PROTECT, related_name="employment_records"
    )
    department = models.ForeignKey(Department, on_delete=models.PROTECT)
    designation = models.ForeignKey(Designation, on_delete=models.PROTECT)
    manager = models.ForeignKey(
        Employee, null=True, blank=True, on_delete=models.PROTECT, related_name="reports"
    )
    employment_type = models.CharField(
        max_length=20,
        choices=[
            (x, x.title()) for x in ["permanent", "contract", "part_time", "temporary", "visiting"]
        ],
    )
    starts_on = models.DateField()
    ends_on = models.DateField(null=True, blank=True)
    probation_ends_on = models.DateField(null=True, blank=True)
    reason = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-starts_on", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_on__isnull=True)
                | models.Q(ends_on__gte=models.F("starts_on")),
                name="hr_employment_dates",
            )
        ]


class Qualification(TimestampedModel):
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="qualifications")
    title = models.CharField(max_length=160)
    institution = models.CharField(max_length=160, blank=True)
    awarded_on = models.DateField(null=True, blank=True)
    expires_on = models.DateField(null=True, blank=True)


class StaffDocument(TimestampedModel):
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="documents")
    kind = models.CharField(max_length=30)
    title = models.CharField(max_length=160)
    filename = models.CharField(max_length=180)
    content_type = models.CharField(max_length=80)
    content = models.BinaryField()
    expires_on = models.DateField(null=True, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)


class EmployeeNote(TimestampedModel):
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="notes")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    text = models.TextField(max_length=4000)


class LeavePolicy(TimestampedModel):
    name = models.CharField(max_length=100, unique=True)
    kind = models.CharField(
        max_length=10,
        default="annual",
        choices=[("annual", "Annual"), ("sick", "Sick"), ("casual", "Casual")],
    )
    annual_days = models.DecimalField(max_digits=6, decimal_places=2)
    carry_forward_days = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    unpaid = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(annual_days__gte=0, carry_forward_days__gte=0),
                name="hr_leave_policy_nonnegative",
            )
        ]


class LeaveEntitlement(TimestampedModel):
    employee = models.ForeignKey(
        Employee, on_delete=models.PROTECT, related_name="leave_entitlements"
    )
    policy = models.ForeignKey(LeavePolicy, on_delete=models.PROTECT)
    year = models.PositiveIntegerField()
    days = models.DecimalField(max_digits=6, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "policy", "year"], name="hr_unique_entitlement"
            ),
            models.CheckConstraint(
                condition=models.Q(days__gte=0), name="hr_leave_days_nonnegative"
            ),
        ]


class ReviewPeriod(TimestampedModel):
    name = models.CharField(max_length=100)
    starts_on = models.DateField()
    ends_on = models.DateField()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_on__gte=models.F("starts_on")), name="hr_review_dates"
            )
        ]


class PerformanceReview(TimestampedModel):
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="reviews")
    period = models.ForeignKey(ReviewPeriod, on_delete=models.PROTECT)
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    criteria = models.JSONField(default=dict)
    comments = models.TextField(max_length=5000, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["employee", "period"], name="hr_unique_review")
        ]


class TrainingProgram(TimestampedModel):
    title = models.CharField(max_length=160)
    starts_on = models.DateField()
    ends_on = models.DateField()
    provider = models.CharField(max_length=160, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_on__gte=models.F("starts_on")), name="hr_training_dates"
            )
        ]


class TrainingRecord(TimestampedModel):
    program = models.ForeignKey(TrainingProgram, on_delete=models.PROTECT)
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="training")
    status = models.CharField(
        max_length=20,
        choices=[(x, x.title()) for x in ["planned", "attended", "completed", "cancelled"]],
    )
    certificate_expires_on = models.DateField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["program", "employee"], name="hr_unique_training")
        ]
