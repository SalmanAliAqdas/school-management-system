import uuid
from decimal import Decimal

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateRangeField
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from core.models import TimestampedModel

ZERO = Decimal("0")
LIMIT = Decimal("99999999999999.999")


def money(default=ZERO, **kwargs):
    return models.DecimalField(max_digits=18, decimal_places=3, default=default, **kwargs)


def nonnegative(field, positive=False):
    return models.Q(**{f"{field}__gt" if positive else f"{field}__gte": 0, f"{field}__lte": LIMIT})


def ordered_dates():
    return models.Q(ends_on__gte=models.F("starts_on"))


def date_range():
    return models.Func(
        "starts_on",
        "ends_on",
        models.Value("[]"),
        function="DATERANGE",
        output_field=DateRangeField(),
    )


class FinanceSettings(TimestampedModel):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    currency = models.CharField(max_length=3)
    symbol = models.CharField(max_length=8, default="", blank=True)
    decimal_places = models.PositiveSmallIntegerField(default=2, validators=[MaxValueValidator(3)])
    year_start_month = models.PositiveSmallIntegerField(
        default=7, validators=[MinValueValidator(1), MaxValueValidator(12)]
    )
    due_day = models.PositiveSmallIntegerField(
        default=10, validators=[MinValueValidator(1), MaxValueValidator(28)]
    )
    shift_holiday_due_dates = models.BooleanField(default=False)
    invoice_format = models.CharField(max_length=50, default="INV/{year}/{seq:06d}")
    receipt_format = models.CharField(max_length=50, default="RCT/{year}/{seq:06d}")
    billing_rule = models.CharField(
        max_length=12,
        default="prorata",
        choices=[
            ("start", "Enrolled at period start"),
            ("any", "Any overlap, full charge"),
            ("prorata", "Calendar-day proration"),
        ],
    )
    invoice_approval = models.BooleanField(default=True)
    payment_approval_threshold = money(Decimal("100000"))
    senior_approval_threshold = money(Decimal("50000"))
    senior_discount_percent = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        default=20,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    allow_discount_stacking = models.BooleanField(default=False)
    discount_ceiling_percent = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        default=100,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    backdate_days = models.PositiveSmallIntegerField(default=7)
    student_portal = models.BooleanField(default=True)
    guardian_portal = models.BooleanField(default=True)
    include_guardian_names = models.BooleanField(default=False)
    reminder_days_before = models.PositiveSmallIntegerField(default=3)
    reminder_repeat_days = models.PositiveSmallIntegerField(default=7)
    fine_mode = models.CharField(
        max_length=10,
        default="none",
        choices=[
            ("none", "Disabled"),
            ("fixed", "Fixed"),
            ("percent", "Percentage of original eligible charge"),
        ],
    )
    fine_value = money()
    fine_cap = money()
    fine_grace_days = models.PositiveSmallIntegerField(default=0)
    fine_repeat_days = models.PositiveSmallIntegerField(
        default=0, help_text="0 means one-time; never compounded."
    )

    class Meta:
        permissions = [
            (code, label)
            for code, label in [
                ("access_finance", "Can access finance"),
                ("view_all_finance", "Can read all student finance records"),
                ("manage_finance", "Can configure finance"),
                ("manage_fees", "Can manage fee structures and assignments"),
                ("generate_invoices", "Can generate and issue approved invoices"),
                ("collect_payments", "Can record manual collections"),
                ("allocate_credit", "Can allocate student credits"),
                ("request_adjustments", "Can request financial corrections"),
                ("approve_finance", "Can independently approve finance requests"),
                ("approve_senior_finance", "Can approve material/backdated finance requests"),
                ("view_finance_reports", "Can view and export financial reports"),
                ("view_journal", "Can inspect the accounting journal"),
                ("record_expenses", "Can request and pay approved expenses"),
                ("reconcile_accounts", "Can prepare manual account reconciliations"),
                ("close_financial_periods", "Can request financial closing"),
                ("reopen_financial_periods", "Can approve controlled financial reopening"),
            ]
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    senior_discount_percent__gte=0,
                    senior_discount_percent__lte=100,
                    discount_ceiling_percent__gte=0,
                    discount_ceiling_percent__lte=100,
                    reminder_repeat_days__gte=1,
                ),
                name="finance_policy_percent_ranges",
            ),
            models.CheckConstraint(condition=models.Q(pk=1), name="finance_single_settings"),
            models.CheckConstraint(
                condition=models.Q(
                    decimal_places__lte=3,
                    year_start_month__gte=1,
                    year_start_month__lte=12,
                    due_day__gte=1,
                    due_day__lte=28,
                ),
                name="finance_setting_ranges",
            ),
            models.CheckConstraint(
                condition=nonnegative("payment_approval_threshold")
                & nonnegative("senior_approval_threshold")
                & nonnegative("fine_value")
                & nonnegative("fine_cap"),
                name="finance_setting_money",
            ),
        ]


class FinancialYear(TimestampedModel):
    name = models.CharField(max_length=60, unique=True)
    starts_on = models.DateField()
    ends_on = models.DateField()
    is_closed = models.BooleanField(default=False)

    class Meta:
        ordering = ["-starts_on"]
        constraints = [
            models.CheckConstraint(condition=ordered_dates(), name="finance_year_dates"),
            ExclusionConstraint(
                name="finance_years_no_overlap", expressions=[(date_range(), "&&")]
            ),
        ]

    def __str__(self):
        return self.name


class FinancialPeriod(TimestampedModel):
    financial_year = models.ForeignKey(
        FinancialYear, on_delete=models.PROTECT, related_name="periods"
    )
    name = models.CharField(max_length=80)
    starts_on = models.DateField()
    ends_on = models.DateField()
    is_closed = models.BooleanField(default=False)

    class Meta:
        ordering = ["-starts_on"]
        constraints = [
            models.CheckConstraint(condition=ordered_dates(), name="finance_period_dates"),
            models.UniqueConstraint(fields=["financial_year", "name"], name="finance_period_name"),
            ExclusionConstraint(
                name="finance_periods_no_overlap", expressions=[(date_range(), "&&")]
            ),
        ]

    def __str__(self):
        return f"{self.financial_year} / {self.name}"


class Account(TimestampedModel):
    code = models.CharField(max_length=24, unique=True)
    name = models.CharField(max_length=100)
    kind = models.CharField(
        max_length=15,
        choices=[
            ("asset", "Asset"),
            ("liability", "Liability"),
            ("equity", "Equity"),
            ("income", "Income"),
            ("contra_income", "Contra income"),
            ("expense", "Expense"),
        ],
    )
    control = models.CharField(
        max_length=16,
        choices=[
            ("cash", "Cash"),
            ("bank", "Bank"),
            ("receivable", "Student receivables"),
            ("revenue", "Fee revenue"),
            ("deferred", "Deferred revenue"),
            ("advance", "Student advances"),
            ("deposit", "Funded refundable deposits"),
            ("deposit_due", "Uncollected deposit charges"),
            ("discount", "Discounts / contra income"),
            ("fine", "Fine income"),
            ("expense", "Expenses"),
            ("payable", "Expense payables"),
            ("adjustment", "Adjustments / write-offs"),
            ("equity", "Opening equity"),
        ],
    )
    is_active = models.BooleanField(default=True)
    bank_name = models.CharField(max_length=100, blank=True)
    account_identifier = models.CharField(
        max_length=80,
        blank=True,
        help_text="Staff-only identifier. Never enter passwords, card details, CVV or PIN.",
    )

    class Meta:
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(
                fields=["control"],
                condition=~models.Q(control__in=["cash", "bank", "revenue", "expense"]),
                name="finance_one_control_account",
            )
        ]

    @property
    def masked_identifier(self):
        return "â€¦" + self.account_identifier[-4:] if self.account_identifier else ""

    def __str__(self):
        return f"{self.code} Â· {self.name}"


class FeeCategory(TimestampedModel):
    name = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=500, blank=True)
    is_active = models.BooleanField(default=True)
    recurring = models.BooleanField(default=True)
    refundable = models.BooleanField(default=False)
    one_time_scope = models.CharField(
        max_length=10,
        default="year",
        choices=[("year", "Once per academic year"), ("student", "Once per student")],
    )
    treatment = models.CharField(
        max_length=12,
        default="earned",
        choices=[
            ("earned", "Earned on issue"),
            ("deferred", "Deferred until recognition"),
            ("deposit", "Refundable deposit"),
            ("opening", "Opening receivable, equity offset"),
        ],
    )
    income_account = models.ForeignKey(Account, on_delete=models.PROTECT)
    starts_on = models.DateField()
    ends_on = models.DateField(null=True, blank=True)
    late_fee_eligible = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_on__isnull=True) | ordered_dates(),
                name="finance_category_dates",
            )
        ]

    def __str__(self):
        return self.name


FREQUENCIES = [
    ("monthly", "Monthly"),
    ("quarterly", "Quarterly"),
    ("term", "Term-wise"),
    ("annual", "Annual"),
    ("once", "One-time"),
    ("custom", "Custom"),
]


class FeeStructure(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    family = models.UUIDField(default=uuid.uuid4, editable=False)
    revision = models.PositiveIntegerField(default=1, editable=False)
    revises = models.OneToOneField(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="next_revision"
    )
    name = models.CharField(max_length=100)
    academic_year = models.ForeignKey("academics.AcademicYear", on_delete=models.PROTECT)
    school_class = models.ForeignKey("academics.SchoolClass", on_delete=models.PROTECT)
    section = models.ForeignKey(
        "academics.Section", on_delete=models.PROTECT, null=True, blank=True
    )
    frequency = models.CharField(max_length=12, choices=FREQUENCIES)
    starts_on = models.DateField()
    ends_on = models.DateField()
    is_active = models.BooleanField(default=True)
    assignment_only = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["family", "revision"], name="finance_structure_revision"
            ),
            models.CheckConstraint(condition=ordered_dates(), name="finance_structure_dates"),
        ]

    def __str__(self):
        return f"{self.name} Â· {self.academic_year} Â· v{self.revision}"


class FeeLine(TimestampedModel):
    structure = models.ForeignKey(FeeStructure, on_delete=models.PROTECT, related_name="lines")
    category = models.ForeignKey(FeeCategory, on_delete=models.PROTECT)
    amount = money()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["structure", "category"], name="finance_structure_category"
            ),
            models.CheckConstraint(
                condition=nonnegative("amount", True), name="finance_fee_amount"
            ),
        ]

    def __str__(self):
        return f"{self.structure.name} Â· {self.category}"


class FeeAssignment(TimestampedModel):
    def __str__(self):
        return f"{self.student} / {self.structure.name} / {self.starts_on}"

    student = models.ForeignKey("people.Student", on_delete=models.PROTECT)
    structure = models.ForeignKey(FeeStructure, on_delete=models.PROTECT)
    category = models.ForeignKey(
        FeeCategory,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Optional single-category override.",
    )
    amount_override = money(None, null=True, blank=True)
    starts_on = models.DateField()
    ends_on = models.DateField()
    reason = models.CharField(max_length=500)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=ordered_dates(), name="finance_assignment_dates"),
            models.CheckConstraint(
                condition=models.Q(amount_override__isnull=True) | nonnegative("amount_override"),
                name="finance_override_amount",
            ),
            models.CheckConstraint(
                condition=~models.Q(reason=""), name="finance_assignment_reason"
            ),
        ]


class ConcessionType(TimestampedModel):
    name = models.CharField(max_length=100, unique=True)
    eligibility = models.CharField(
        max_length=12,
        default="manual",
        choices=[
            ("manual", "Verified by school approver"),
            ("siblings", "At least two currently enrolled linked children"),
        ],
    )
    mode = models.CharField(max_length=10, choices=[("fixed", "Fixed"), ("percent", "Percentage")])
    default_value = money()
    per_charge_cap = money(None, null=True, blank=True)
    stackable = models.BooleanField(default=False)
    one_time = models.BooleanField(default=False)
    priority = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=nonnegative("default_value", True), name="finance_concession_default"
            ),
            models.CheckConstraint(
                condition=models.Q(per_charge_cap__isnull=True) | nonnegative("per_charge_cap"),
                name="finance_concession_cap",
            ),
        ]

    def __str__(self):
        return self.name


class ConcessionAward(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey("people.Student", on_delete=models.PROTECT)
    concession_type = models.ForeignKey(ConcessionType, on_delete=models.PROTECT)
    category = models.ForeignKey(FeeCategory, on_delete=models.PROTECT, null=True, blank=True)
    value = money()
    starts_on = models.DateField()
    ends_on = models.DateField()
    notes = models.CharField(
        max_length=300,
        help_text="Eligibility verification only; omit sensitive personal background.",
    )
    request = models.OneToOneField(
        "FinancialRequest",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="concession_award",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(condition=ordered_dates(), name="finance_award_dates"),
            models.CheckConstraint(
                condition=nonnegative("value", True), name="finance_award_value"
            ),
        ]


class BillingCycle(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    academic_year = models.ForeignKey("academics.AcademicYear", on_delete=models.PROTECT)
    name = models.CharField(max_length=100)
    frequency = models.CharField(max_length=12, choices=FREQUENCIES)
    starts_on = models.DateField()
    ends_on = models.DateField()
    issue_on = models.DateField()
    due_on = models.DateField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["academic_year", "name"], name="finance_cycle_name"),
            models.CheckConstraint(
                condition=ordered_dates() & models.Q(due_on__gte=models.F("issue_on")),
                name="finance_cycle_dates",
            ),
        ]

    def __str__(self):
        return f"{self.name} Â· {self.academic_year}"


class Invoice(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    generation_key = models.CharField(max_length=160, unique=True)
    number = models.CharField(max_length=50, unique=True)
    student = models.ForeignKey(
        "people.Student", on_delete=models.PROTECT, related_name="fee_invoices"
    )
    academic_year = models.ForeignKey("academics.AcademicYear", on_delete=models.PROTECT)
    cycle = models.ForeignKey(BillingCycle, on_delete=models.PROTECT, null=True, blank=True)
    replaces = models.OneToOneField(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="replacement"
    )
    issue_on = models.DateField()
    due_on = models.DateField()
    currency = models.CharField(max_length=3)
    subtotal = money()
    discount = money()
    total = money()
    state = models.CharField(
        max_length=12,
        default="draft",
        choices=[
            ("draft", "Draft"),
            ("approved", "Approved"),
            ("issued", "Issued"),
            ("voided", "Voided"),
        ],
    )
    version = models.PositiveIntegerField(default=0)
    snapshot = models.JSONField(default=dict)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    approval = models.ForeignKey(
        "FinancialRequest",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="approved_invoices",
    )

    class Meta:
        ordering = ["-issue_on", "number"]
        indexes = [
            models.Index(fields=["academic_year", "state", "due_on"], name="finance_invoice_lookup")
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "cycle"],
                condition=models.Q(replaces__isnull=True, cycle__isnull=False),
                name="finance_original_invoice_cycle",
            ),
            models.CheckConstraint(
                condition=nonnegative("subtotal")
                & nonnegative("discount")
                & nonnegative("total")
                & models.Q(total=models.F("subtotal") - models.F("discount")),
                name="finance_invoice_arithmetic",
            ),
            models.CheckConstraint(
                condition=models.Q(due_on__gte=models.F("issue_on")), name="finance_invoice_due"
            ),
        ]

    def __str__(self):
        return self.number


class InvoiceLine(TimestampedModel):
    def __str__(self):
        return f"{self.invoice.number} / {self.description} / {self.pk}"

    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="lines")
    category = models.ForeignKey(FeeCategory, on_delete=models.PROTECT)
    enrollment = models.ForeignKey("people.Enrollment", on_delete=models.PROTECT)
    fee_line = models.ForeignKey(FeeLine, on_delete=models.PROTECT, null=True, blank=True)
    assignment = models.ForeignKey(FeeAssignment, on_delete=models.PROTECT, null=True, blank=True)
    description = models.CharField(max_length=250)
    gross = money()
    discount = money()
    net = money()
    details = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=nonnegative("gross")
                & nonnegative("discount")
                & nonnegative("net")
                & models.Q(net=models.F("gross") - models.F("discount")),
                name="finance_line_arithmetic",
            )
        ]


class OneTimeCharge(TimestampedModel):
    student = models.ForeignKey("people.Student", on_delete=models.PROTECT)
    category = models.ForeignKey(FeeCategory, on_delete=models.PROTECT)
    academic_year = models.ForeignKey(
        "academics.AcademicYear", on_delete=models.PROTECT, null=True, blank=True
    )
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["student", "category", "academic_year"],
                nulls_distinct=False,
                name="finance_one_time_charge",
            )
        ]


class ConcessionUse(TimestampedModel):
    award = models.ForeignKey(ConcessionAward, on_delete=models.PROTECT)
    invoice_line = models.ForeignKey(InvoiceLine, on_delete=models.PROTECT)
    amount = money()
    once_key = models.UUIDField(null=True, blank=True, unique=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["award", "invoice_line"], name="finance_concession_use"
            ),
            models.CheckConstraint(
                condition=nonnegative("amount", True), name="finance_concession_use_positive"
            ),
        ]


class PaymentMethod(TimestampedModel):
    name = models.CharField(max_length=80, unique=True)
    is_active = models.BooleanField(default=True)
    account = models.ForeignKey(Account, on_delete=models.PROTECT)

    def __str__(self):
        return self.name


class Payment(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    idempotency_key = models.UUIDField(unique=True)
    fingerprint = models.CharField(max_length=64)
    number = models.CharField(max_length=50, blank=True)
    student = models.ForeignKey(
        "people.Student", on_delete=models.PROTECT, related_name="fee_payments"
    )
    paid_on = models.DateField()
    amount = money()
    method = models.ForeignKey(PaymentMethod, on_delete=models.PROTECT)
    reference = models.CharField(
        max_length=100, help_text="Unique source/slip reference. Never enter card credentials."
    )
    notes = models.CharField(max_length=300, blank=True)
    state = models.CharField(
        max_length=12,
        default="pending",
        choices=[
            ("pending", "Awaiting approval"),
            ("posted", "Posted, manually recorded"),
            ("rejected", "Rejected"),
        ],
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="collected_payments"
    )
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="posted_payments",
    )
    posted_at = models.DateTimeField(null=True, blank=True)
    snapshot = models.JSONField(default=dict)

    class Meta:
        ordering = ["-paid_on", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["number"], condition=~models.Q(number=""), name="finance_receipt_number"
            ),
            models.UniqueConstraint(
                fields=["method", "reference"], name="finance_payment_reference"
            ),
            models.CheckConstraint(
                condition=nonnegative("amount", True), name="finance_payment_amount"
            ),
        ]


class CreditLot(TimestampedModel):
    def __str__(self):
        return f"{self.student} / credit {self.amount} / {str(self.pk)[:8]}"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(
        "people.Student", on_delete=models.PROTECT, related_name="credit_lots"
    )
    payment = models.OneToOneField(
        Payment, on_delete=models.PROTECT, null=True, blank=True, related_name="credit_lot"
    )
    opening_request = models.OneToOneField(
        "FinancialRequest",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="opening_credit",
    )
    amount = money()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=nonnegative("amount", True), name="finance_credit_amount"
            ),
            models.CheckConstraint(
                condition=models.Q(payment__isnull=False, opening_request__isnull=True)
                | models.Q(payment__isnull=True, opening_request__isnull=False),
                name="finance_credit_source",
            ),
        ]


class Allocation(TimestampedModel):
    def __str__(self):
        return f"{self.invoice.number} / {self.amount} / {str(self.pk)[:8]}"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    credit = models.ForeignKey(CreditLot, on_delete=models.PROTECT, related_name="allocations")
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="allocations")
    line = models.ForeignKey(
        InvoiceLine, on_delete=models.PROTECT, null=True, blank=True, related_name="allocations"
    )
    charge = models.ForeignKey(
        "InvoiceAdjustment",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="allocations",
    )
    amount = money()
    allocated_on = models.DateField()
    source_key = models.CharField(max_length=180, unique=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=nonnegative("amount", True), name="finance_allocation_amount"
            ),
            models.CheckConstraint(
                condition=models.Q(line__isnull=False, charge__isnull=True)
                | models.Q(line__isnull=True, charge__isnull=False),
                name="finance_allocation_target",
            ),
        ]


class AllocationRelease(TimestampedModel):
    allocation = models.ForeignKey(Allocation, on_delete=models.PROTECT, related_name="releases")
    request = models.ForeignKey("FinancialRequest", on_delete=models.PROTECT)
    amount = money()
    source_key = models.CharField(max_length=180, unique=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=nonnegative("amount", True), name="finance_release_amount"
            )
        ]


class InvoiceAdjustment(TimestampedModel):
    def __str__(self):
        return f"{self.invoice.number} / {self.kind} / {self.amount}"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="adjustments")
    line = models.ForeignKey(
        InvoiceLine, on_delete=models.PROTECT, null=True, blank=True, related_name="adjustments"
    )
    reverses_charge = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="credits"
    )
    kind = models.CharField(
        max_length=12,
        choices=[
            ("fine", "Late fee"),
            ("debit", "Authorized charge"),
            ("credit", "Credit note"),
            ("writeoff", "Write-off"),
            ("waiver", "Fine waiver"),
        ],
    )
    amount = money()
    occurred_on = models.DateField()
    reason = models.CharField(max_length=500)
    request = models.ForeignKey("FinancialRequest", on_delete=models.PROTECT, null=True, blank=True)
    source_key = models.CharField(max_length=180, unique=True)
    details = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(kind__in=["fine", "debit"], amount__gt=0)
                    | models.Q(kind__in=["credit", "writeoff", "waiver"], amount__lt=0)
                ),
                name="finance_adjustment_sign",
            )
        ]


class RevenueRecognition(TimestampedModel):
    line = models.ForeignKey(InvoiceLine, on_delete=models.PROTECT, related_name="recognitions")
    request = models.ForeignKey("FinancialRequest", on_delete=models.PROTECT)
    amount = money()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(amount=0), name="finance_recognition_nonzero"
            )
        ]


class ExpenseCategory(TimestampedModel):
    name = models.CharField(max_length=100, unique=True)
    account = models.ForeignKey(Account, on_delete=models.PROTECT)

    def __str__(self):
        return self.name


class Expense(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT)
    occurred_on = models.DateField()
    payee = models.CharField(max_length=140)
    amount = money()
    description = models.CharField(max_length=500)
    attachment = models.FileField(upload_to="private/finance/", blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    request = models.OneToOneField(
        "FinancialRequest",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="expense_document",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=nonnegative("amount", True), name="finance_expense_positive"
            )
        ]


class ExpensePayment(TimestampedModel):
    expense = models.OneToOneField(Expense, on_delete=models.PROTECT, related_name="payment")
    account = models.ForeignKey(Account, on_delete=models.PROTECT)
    paid_on = models.DateField()
    reference = models.CharField(max_length=100, unique=True)
    paid_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)


REQUEST_KINDS = [
    (key, label)
    for key, label in [
        ("issue_invoice", "Invoice approval"),
        ("payment", "Payment approval"),
        ("discount", "Concession approval"),
        ("exempt_fines", "Late-fee exemption approval"),
        ("credit", "Invoice credit / adjustment"),
        ("debit", "Additional invoice charge"),
        ("writeoff", "Receivable write-off"),
        ("void", "Void unpaid invoice"),
        ("replace", "Replacement invoice"),
        ("fine_waiver", "Fine waiver"),
        ("refund_credit", "Advance credit refund"),
        ("refund_deposit", "Refundable deposit return"),
        ("refund_fee", "Paid refundable fee refund"),
        ("reverse_payment", "Payment / returned cheque reversal"),
        ("expense", "Expense approval"),
        ("transfer", "Cash / bank transfer"),
        ("opening", "Cash / bank opening"),
        ("opening_student", "Student opening account"),
        ("recognize", "Deferred revenue recognition"),
        ("allocate", "Backdated credit allocation"),
        ("reconcile", "Manual reconciliation"),
        ("close_period", "Financial period closing"),
        ("reopen_period", "Financial period reopening"),
        ("close_year", "Financial year closing"),
        ("reopen_year", "Financial year reopening"),
    ]
]


class FinancialRequest(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=20, choices=REQUEST_KINDS)
    student = models.ForeignKey("people.Student", on_delete=models.PROTECT, null=True, blank=True)
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, null=True, blank=True)
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, null=True, blank=True)
    credit = models.ForeignKey(CreditLot, on_delete=models.PROTECT, null=True, blank=True)
    allocation = models.ForeignKey(Allocation, on_delete=models.PROTECT, null=True, blank=True)
    line = models.ForeignKey(InvoiceLine, on_delete=models.PROTECT, null=True, blank=True)
    charge = models.ForeignKey(InvoiceAdjustment, on_delete=models.PROTECT, null=True, blank=True)
    period = models.ForeignKey(FinancialPeriod, on_delete=models.PROTECT, null=True, blank=True)
    source_account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="source_finance_requests",
    )
    target_account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="target_finance_requests",
    )
    amount = money()
    occurred_on = models.DateField()
    reason = models.CharField(max_length=1000)
    payload = models.JSONField(default=dict)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="finance_requests"
    )
    state = models.CharField(
        max_length=10,
        default="pending",
        choices=[
            ("pending", "Awaiting approval"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="finance_decisions",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    decision_reason = models.CharField(max_length=1000, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["state", "kind"], name="finance_request_queue")]
        constraints = [
            models.CheckConstraint(condition=nonnegative("amount"), name="finance_request_amount"),
            models.CheckConstraint(condition=~models.Q(reason=""), name="finance_request_reason"),
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
                name="finance_independent_decision",
            ),
        ]


class JournalEntry(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_key = models.CharField(max_length=180, unique=True)
    source_type = models.CharField(max_length=30)
    source_id = models.CharField(max_length=64)
    occurred_on = models.DateField(db_index=True)
    period = models.ForeignKey(FinancialPeriod, on_delete=models.PROTECT, related_name="journals")
    currency = models.CharField(max_length=3)
    memo = models.CharField(max_length=300)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    request = models.ForeignKey(FinancialRequest, on_delete=models.PROTECT, null=True, blank=True)
    reversal_of = models.OneToOneField(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="reversal"
    )
    state = models.CharField(
        max_length=8, default="draft", choices=[("draft", "Preparing"), ("posted", "Posted")]
    )

    class Meta:
        ordering = ["occurred_on", "created_at"]


class JournalLine(TimestampedModel):
    def __str__(self):
        return (
            f"{self.journal.occurred_on} / {self.account.name} / "
            f"Dr {self.debit} Cr {self.credit} / {self.pk}"
        )

    journal = models.ForeignKey(JournalEntry, on_delete=models.PROTECT, related_name="lines")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="journal_lines")
    student = models.ForeignKey("people.Student", on_delete=models.PROTECT, null=True, blank=True)
    debit = money()
    credit = money()

    class Meta:
        indexes = [models.Index(fields=["student", "account"], name="finance_student_control_idx")]
        constraints = [
            models.CheckConstraint(
                condition=(models.Q(debit__gt=0, credit=0) | models.Q(credit__gt=0, debit=0))
                & nonnegative("debit")
                & nonnegative("credit"),
                name="finance_journal_line_side",
            )
        ]


class Refund(TimestampedModel):
    request = models.ForeignKey(FinancialRequest, on_delete=models.PROTECT, related_name="refunds")
    student = models.ForeignKey("people.Student", on_delete=models.PROTECT)
    credit = models.ForeignKey(
        CreditLot, on_delete=models.PROTECT, null=True, blank=True, related_name="refunds"
    )
    allocation = models.ForeignKey(
        Allocation, on_delete=models.PROTECT, null=True, blank=True, related_name="deposit_refunds"
    )
    amount = money()
    account = models.ForeignKey(Account, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=nonnegative("amount", True), name="finance_refund_amount"
            ),
            models.CheckConstraint(
                condition=models.Q(credit__isnull=False, allocation__isnull=True)
                | models.Q(credit__isnull=True, allocation__isnull=False),
                name="finance_refund_source",
            ),
        ]


class Reconciliation(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request = models.OneToOneField(
        FinancialRequest, on_delete=models.PROTECT, related_name="reconciliation"
    )
    account = models.ForeignKey(Account, on_delete=models.PROTECT)
    starts_on = models.DateField()
    ends_on = models.DateField()
    opening_statement = money()
    closing_statement = money()

    class Meta:
        constraints = [
            models.CheckConstraint(condition=ordered_dates(), name="finance_reconciliation_dates")
        ]


class ReconciliationLine(TimestampedModel):
    reconciliation = models.ForeignKey(
        Reconciliation, on_delete=models.PROTECT, related_name="lines"
    )
    line = models.ForeignKey(
        JournalLine, on_delete=models.PROTECT, related_name="reconciliation_links"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["line"],
                condition=models.Q(is_active=True),
                name="finance_one_active_clearing",
            ),
            models.UniqueConstraint(
                fields=["reconciliation", "line"], name="finance_reconciliation_line"
            ),
        ]


class PeriodEvent(TimestampedModel):
    request = models.OneToOneField(FinancialRequest, on_delete=models.PROTECT)
    snapshot = models.JSONField(default=dict)


class DocumentCounter(models.Model):
    kind = models.CharField(max_length=10)
    year = models.PositiveSmallIntegerField()
    next_number = models.PositiveBigIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["kind", "year"], name="finance_document_counter")
        ]


class FinanceEvent(TimestampedModel):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    action = models.CharField(max_length=50)
    target = models.CharField(max_length=80)
    student = models.ForeignKey("people.Student", on_delete=models.PROTECT, null=True, blank=True)
    reason = models.CharField(max_length=1000, blank=True)

    class Meta:
        ordering = ["-created_at"]


class FinanceNotice(TimestampedModel):
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    student = models.ForeignKey("people.Student", on_delete=models.PROTECT)
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, null=True, blank=True)
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, null=True, blank=True)
    kind = models.CharField(max_length=30)
    event_key = models.CharField(max_length=180)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "student", "event_key"], name="finance_notice_once"
            )
        ]


class LateFeeExemption(TimestampedModel):
    student = models.ForeignKey("people.Student", on_delete=models.PROTECT)
    starts_on = models.DateField()
    ends_on = models.DateField()
    request = models.OneToOneField(FinancialRequest, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=ordered_dates(), name="finance_exemption_dates")
        ]
