import uuid

from django.conf import settings
from django.db import models

from core.models import TimestampedModel


class Component(TimestampedModel):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=20, unique=True)
    kind = models.CharField(
        max_length=16,
        choices=[
            ("earning", "Earning"),
            ("deduction", "Deduction"),
            ("reimbursement", "Reimbursement"),
            ("recovery", "Recovery"),
        ],
    )
    account = models.ForeignKey("finance.Account", on_delete=models.PROTECT)
    is_active = models.BooleanField(default=True)


class PayrollSettings(TimestampedModel):
    currency = models.CharField(max_length=3, default="PKR")
    salary_payable_account = models.ForeignKey(
        "finance.Account", on_delete=models.PROTECT, related_name="payroll_payable_settings"
    )
    payment_account = models.ForeignKey(
        "finance.Account", on_delete=models.PROTECT, related_name="payroll_payment_settings"
    )
    independent_approval = models.BooleanField(default=True)


class SalaryRevision(TimestampedModel):
    employee = models.ForeignKey(
        "hr.Employee", on_delete=models.PROTECT, related_name="salary_revisions"
    )
    component = models.ForeignKey(Component, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    authorized_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gte=0), name="payroll_revision_nonnegative"
            )
        ]


class PayrollPeriod(TimestampedModel):
    name = models.CharField(max_length=80, unique=True)
    starts_on = models.DateField()
    ends_on = models.DateField()
    payment_date = models.DateField()
    proration = models.CharField(
        max_length=20,
        default="calendar_days",
        choices=[("calendar_days", "Calendar days"), ("working_days", "Configured working days")],
    )
    state = models.CharField(
        max_length=16,
        default="open",
        choices=[(x, x.title()) for x in ["open", "submitted", "approved", "finalized", "closed"]],
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_on__gte=models.F("starts_on")),
                name="payroll_period_dates",
            )
        ]


class PayrollRun(TimestampedModel):
    period = models.OneToOneField(PayrollPeriod, on_delete=models.PROTECT, related_name="run")
    prepared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="prepared_payroll"
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reviewed_payroll",
    )
    state = models.CharField(
        max_length=16,
        default="draft",
        choices=[
            (x, x.title()) for x in ["draft", "submitted", "approved", "finalized", "reversed"]
        ],
    )
    reason = models.CharField(max_length=500, blank=True)
    reversal_journal = models.OneToOneField(
        "finance.JournalEntry",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reversed_payroll_run",
    )
    reversed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        permissions = [
            ("manage_payroll", "Prepare payroll"),
            ("approve_payroll", "Approve payroll"),
            ("pay_payroll", "Record payroll payments"),
            ("view_all_payroll", "View all payroll"),
        ]


class Payslip(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(PayrollRun, on_delete=models.PROTECT, related_name="payslips")
    employee = models.ForeignKey("hr.Employee", on_delete=models.PROTECT, related_name="payslips")
    reference = models.CharField(max_length=40, unique=True)
    state = models.CharField(
        max_length=16,
        default="draft",
        choices=[(x, x.title()) for x in ["draft", "held", "released", "paid", "reversed"]],
    )
    gross = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    deductions = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    net = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    snapshot = models.JSONField(default=dict)
    journal = models.OneToOneField(
        "finance.JournalEntry", null=True, blank=True, on_delete=models.PROTECT
    )
    payment_journal = models.OneToOneField(
        "finance.JournalEntry",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="paid_payslip",
    )
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["run", "employee"], name="payroll_one_employee_period"),
            models.CheckConstraint(
                condition=models.Q(gross__gte=0, deductions__gte=0, net__gte=0),
                name="payroll_nonnegative_totals",
            ),
            models.CheckConstraint(
                condition=models.Q(net=models.F("gross") - models.F("deductions")),
                name="payroll_totals_reconcile",
            ),
        ]


class PayslipLine(TimestampedModel):
    payslip = models.ForeignKey(Payslip, on_delete=models.PROTECT, related_name="lines")
    component = models.ForeignKey(Component, on_delete=models.PROTECT)
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=16)
    amount = models.DecimalField(max_digits=14, decimal_places=2)


class PayrollAction(TimestampedModel):
    run = models.ForeignKey(PayrollRun, on_delete=models.PROTECT, related_name="actions")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    action = models.CharField(max_length=30)
    reason = models.CharField(max_length=500, blank=True)
