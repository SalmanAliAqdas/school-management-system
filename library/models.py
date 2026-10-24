from django.db import models

from core.models import TimestampedModel


class Category(TimestampedModel):
    name = models.CharField(max_length=100, unique=True)


class Location(TimestampedModel):
    name = models.CharField(max_length=100, unique=True)
    shelf = models.CharField(max_length=80, blank=True)


class Book(TimestampedModel):
    title = models.CharField(max_length=240)
    authors = models.CharField(max_length=240)
    isbn = models.CharField(max_length=20, blank=True)
    publisher = models.CharField(max_length=160, blank=True)
    edition = models.CharField(max_length=80, blank=True)
    language = models.CharField(max_length=60, default="English")
    description = models.TextField(max_length=4000, blank=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT)

    class Meta:
        indexes = [models.Index(fields=["title"]), models.Index(fields=["isbn"])]


class Copy(TimestampedModel):
    book = models.ForeignKey(Book, on_delete=models.PROTECT, related_name="copies")
    accession_number = models.CharField(max_length=40, unique=True)
    location = models.ForeignKey(Location, on_delete=models.PROTECT)
    condition = models.CharField(
        max_length=20,
        default="good",
        choices=[(x, x.title()) for x in ["new", "good", "worn", "damaged", "lost"]],
    )
    status = models.CharField(
        max_length=20,
        default="available",
        choices=[
            (x, x.title()) for x in ["available", "issued", "reserved", "repair", "lost", "retired"]
        ],
    )


class Policy(TimestampedModel):
    name = models.CharField(max_length=100, unique=True)
    borrower_kind = models.CharField(
        max_length=12, choices=[("student", "Student"), ("staff", "Staff")]
    )
    loan_days = models.PositiveIntegerField(default=14)
    limit = models.PositiveIntegerField(default=3)
    renewal_limit = models.PositiveIntegerField(default=1)
    grace_days = models.PositiveIntegerField(default=0)
    daily_fine = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    fine_cap = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)


class Membership(TimestampedModel):
    student = models.OneToOneField(
        "people.Student", null=True, blank=True, on_delete=models.PROTECT
    )
    employee = models.OneToOneField("hr.Employee", null=True, blank=True, on_delete=models.PROTECT)
    policy = models.ForeignKey(Policy, on_delete=models.PROTECT)
    is_active = models.BooleanField(default=True)
    suspended_reason = models.CharField(max_length=300, blank=True)

    class Meta:
        permissions = [
            ("manage_library", "Manage library circulation"),
            ("view_all_library", "View all library records"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(student__isnull=False, employee__isnull=True)
                    | models.Q(student__isnull=True, employee__isnull=False)
                ),
                name="library_one_borrower",
            )
        ]


class Loan(TimestampedModel):
    copy = models.ForeignKey(Copy, on_delete=models.PROTECT, related_name="loans")
    membership = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name="loans")
    issued_at = models.DateTimeField()
    due_at = models.DateTimeField()
    returned_at = models.DateTimeField(null=True, blank=True)
    renewals = models.PositiveIntegerField(default=0)
    state = models.CharField(
        max_length=16,
        default="issued",
        choices=[(x, x.title()) for x in ["issued", "returned", "lost", "damaged"]],
    )
    issued_by = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="issued_library_loans"
    )
    returned_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="returned_library_loans",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["copy"], condition=models.Q(state="issued"), name="library_one_active_loan"
            )
        ]


class Reservation(TimestampedModel):
    book = models.ForeignKey(Book, on_delete=models.PROTECT, related_name="reservations")
    membership = models.ForeignKey(
        Membership, on_delete=models.PROTECT, related_name="reservations"
    )
    state = models.CharField(
        max_length=16,
        default="queued",
        choices=[
            (x, x.title()) for x in ["queued", "available", "fulfilled", "cancelled", "expired"]
        ],
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["book", "membership"],
                condition=models.Q(state__in=["queued", "available"]),
                name="library_one_reservation",
            )
        ]


class Fine(TimestampedModel):
    loan = models.ForeignKey(Loan, on_delete=models.PROTECT, related_name="fines")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    kind = models.CharField(max_length=20)
    state = models.CharField(
        max_length=16,
        default="assessed",
        choices=[(x, x.title()) for x in ["assessed", "waived", "paid"]],
    )
    reason = models.CharField(max_length=300, blank=True)
    reviewed_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.PROTECT
    )
