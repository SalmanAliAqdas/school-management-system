from django.db import models

from core.models import TimestampedModel


class Vehicle(TimestampedModel):
    identifier = models.CharField(max_length=40, unique=True)
    registration = models.CharField(max_length=80, unique=True)
    kind = models.CharField(max_length=40)
    capacity = models.PositiveIntegerField()
    status = models.CharField(
        max_length=16,
        default="active",
        choices=[(x, x.title()) for x in ["active", "maintenance", "inactive", "retired"]],
    )
    insurance_expires_on = models.DateField(null=True, blank=True)


class Route(TimestampedModel):
    name = models.CharField(max_length=120, unique=True)
    is_active = models.BooleanField(default=True)


class Stop(TimestampedModel):
    route = models.ForeignKey(Route, on_delete=models.PROTECT, related_name="stops")
    name = models.CharField(max_length=140)
    sequence = models.PositiveIntegerField()

    class Meta:
        ordering = ["sequence"]
        constraints = [
            models.UniqueConstraint(fields=["route", "sequence"], name="transport_stop_order")
        ]


class Trip(TimestampedModel):
    route = models.ForeignKey(Route, on_delete=models.PROTECT, related_name="trips")
    direction = models.CharField(
        max_length=12, choices=[("morning", "Morning"), ("afternoon", "Afternoon")]
    )
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT)
    driver = models.ForeignKey(
        "hr.Employee", on_delete=models.PROTECT, related_name="driving_trips"
    )
    attendant = models.ForeignKey(
        "hr.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="attending_trips",
    )
    starts_at = models.TimeField()
    ends_at = models.TimeField()
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)

    class Meta:
        permissions = [
            ("manage_transport", "Manage transport operations"),
            ("view_all_transport", "View all transport records"),
        ]


class StudentAssignment(TimestampedModel):
    student = models.ForeignKey(
        "people.Student", on_delete=models.PROTECT, related_name="transport_assignments"
    )
    trip = models.ForeignKey(Trip, on_delete=models.PROTECT, related_name="student_assignments")
    pickup_stop = models.ForeignKey(
        Stop, on_delete=models.PROTECT, related_name="pickup_assignments"
    )
    dropoff_stop = models.ForeignKey(
        Stop, on_delete=models.PROTECT, related_name="dropoff_assignments"
    )
    starts_on = models.DateField()
    ends_on = models.DateField(null=True, blank=True)
    guardian_contact_allowed = models.BooleanField(default=True)
    fee_assignment = models.ForeignKey(
        "finance.FeeAssignment", null=True, blank=True, on_delete=models.PROTECT
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["student", "trip"],
                condition=models.Q(ends_on__isnull=True),
                name="transport_active_student_trip",
            )
        ]


class VehicleRecord(TimestampedModel):
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT, related_name="records")
    kind = models.CharField(
        max_length=20, choices=[(x, x.title()) for x in ["inspection", "maintenance", "service"]]
    )
    occurred_on = models.DateField()
    next_due_on = models.DateField(null=True, blank=True)
    details = models.TextField(max_length=3000)
    recorded_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT)


class Incident(TimestampedModel):
    trip = models.ForeignKey(Trip, on_delete=models.PROTECT, related_name="incidents")
    occurred_at = models.DateTimeField()
    kind = models.CharField(max_length=30)
    details = models.TextField(max_length=4000)
    follow_up = models.TextField(max_length=4000, blank=True)
    recorded_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT)


class RouteNotice(TimestampedModel):
    trip = models.ForeignKey(Trip, on_delete=models.PROTECT, related_name="notices")
    service_date = models.DateField()
    state = models.CharField(
        max_length=16,
        choices=[("delayed", "Delayed"), ("cancelled", "Cancelled"), ("changed", "Changed")],
    )
    message = models.CharField(max_length=500)
