from django.db import models

from core.models import TimestampedModel


class Category(TimestampedModel):
    name = models.CharField(max_length=100, unique=True)
    kind = models.CharField(
        max_length=16, choices=[("consumable", "Consumable"), ("asset", "Asset")]
    )


class Location(TimestampedModel):
    name = models.CharField(max_length=120, unique=True)
    is_active = models.BooleanField(default=True)


class Item(TimestampedModel):
    category = models.ForeignKey(Category, on_delete=models.PROTECT)
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=160)
    unit = models.CharField(max_length=30)
    minimum_stock = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    supplier_reference = models.CharField(max_length=160, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(minimum_stock__gte=0), name="inventory_minimum_nonnegative"
            )
        ]


class StockMovement(TimestampedModel):
    reference = models.CharField(max_length=50, unique=True)
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="movements")
    kind = models.CharField(
        max_length=16,
        choices=[
            (x, x.title())
            for x in [
                "opening",
                "receipt",
                "issue",
                "return",
                "transfer",
                "adjustment",
                "correction",
            ]
        ],
    )
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    from_location = models.ForeignKey(
        Location, null=True, blank=True, on_delete=models.PROTECT, related_name="stock_out"
    )
    to_location = models.ForeignKey(
        Location, null=True, blank=True, on_delete=models.PROTECT, related_name="stock_in"
    )
    occurred_on = models.DateField()
    state = models.CharField(
        max_length=16,
        default="draft",
        choices=[("draft", "Draft"), ("finalized", "Finalized"), ("reversed", "Reversed")],
    )
    reason = models.CharField(max_length=500, blank=True)
    actor = models.ForeignKey("accounts.User", on_delete=models.PROTECT)
    reverses = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="reversal"
    )
    expense = models.ForeignKey("finance.Expense", null=True, blank=True, on_delete=models.PROTECT)

    class Meta:
        permissions = [
            ("manage_inventory", "Manage inventory and assets"),
            ("approve_inventory", "Approve inventory adjustments and disposal"),
            ("view_all_inventory", "View all inventory records"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(quantity=0), name="inventory_quantity_nonzero"
            )
        ]


class Asset(TimestampedModel):
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="assets")
    identifier = models.CharField(max_length=50, unique=True)
    acquired_on = models.DateField()
    cost = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    location = models.ForeignKey(Location, on_delete=models.PROTECT)
    custodian = models.ForeignKey(
        "hr.Employee", null=True, blank=True, on_delete=models.PROTECT, related_name="assets"
    )
    condition = models.CharField(max_length=20, default="good")
    warranty_ends_on = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        default="active",
        choices=[(x, x.title()) for x in ["active", "maintenance", "disposed", "lost"]],
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(cost__isnull=True) | models.Q(cost__gte=0),
                name="inventory_asset_cost_nonnegative",
            )
        ]


class AssetEvent(TimestampedModel):
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="events")
    kind = models.CharField(
        max_length=20,
        choices=[
            (x, x.title())
            for x in [
                "acquired",
                "assigned",
                "transferred",
                "maintenance",
                "disposal_requested",
                "disposed",
            ]
        ],
    )
    occurred_on = models.DateField()
    details = models.CharField(max_length=1000)
    actor = models.ForeignKey("accounts.User", on_delete=models.PROTECT)
    approved_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="approved_asset_events",
    )
