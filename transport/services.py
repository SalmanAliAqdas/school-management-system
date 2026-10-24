from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q

from audit.services import record_event

from .models import Trip


def require(actor):
    if not actor.is_active or not actor.has_perm("transport.manage_transport"):
        raise PermissionDenied


def validate_trip(trip):
    if trip.ends_at <= trip.starts_at or trip.vehicle.status != "active":
        raise ValidationError("Trip times and active vehicle are required.")
    if trip.driver.status not in ("active", "probation"):
        raise ValidationError("The driver is not currently eligible.")
    overlap = (
        Trip.objects.filter(
            direction=trip.direction, effective_from__lte=trip.effective_to or trip.effective_from
        )
        .exclude(pk=trip.pk)
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=trip.effective_from))
        .filter(Q(vehicle=trip.vehicle) | Q(driver=trip.driver))
        .filter(starts_at__lt=trip.ends_at, ends_at__gt=trip.starts_at)
    )
    if overlap.exists():
        raise ValidationError("Vehicle or driver has a conflicting trip.")


@transaction.atomic
def save_trip(actor, trip):
    require(actor)
    validate_trip(trip)
    trip.full_clean()
    trip.save()
    record_event("transport.trip_saved", actor=actor, target=trip.pk)
    return trip


@transaction.atomic
def assign_student(actor, assignment):
    require(actor)
    trip = (
        Trip.objects.select_for_update()
        .select_related("vehicle", "route")
        .get(pk=assignment.trip_id)
    )
    if (
        assignment.pickup_stop.route_id != trip.route_id
        or assignment.dropoff_stop.route_id != trip.route_id
    ):
        raise ValidationError("Stops must belong to the assigned route.")
    active = trip.student_assignments.select_for_update().filter(ends_on__isnull=True).count()
    if not assignment.pk and active >= trip.vehicle.capacity:
        raise ValidationError("Vehicle capacity has been reached.")
    assignment.full_clean()
    assignment.save()
    record_event("transport.student_assigned", actor=actor, target=assignment.pk)
    return assignment
