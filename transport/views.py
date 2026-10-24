from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from people.models import GuardianStudent

from .forms import AssignmentForm
from .models import StudentAssignment, Trip, Vehicle
from .services import assign_student


@login_required
def overview(request):
    assignments = StudentAssignment.objects.select_related(
        "student", "trip__route", "pickup_stop", "dropoff_stop"
    )
    if not request.user.has_perm("transport.view_all_transport"):
        student_ids = list(
            GuardianStudent.objects.filter(guardian__user=request.user).values_list(
                "student_id", flat=True
            )
        )
        if hasattr(request.user, "student_profile"):
            student_ids.append(request.user.student_profile.pk)
        assignments = assignments.filter(student_id__in=student_ids)
        if not student_ids and not (
            request.user.has_perm("accounts.access_student_dashboard")
            or request.user.has_perm("accounts.access_parent_dashboard")
        ):
            raise PermissionDenied
    return render(
        request,
        "operations/phase8_dashboard.html",
        {
            "title": "School transport",
            "description": (
                "Route assignments, vehicles and manually reported service information—"
                "no live tracking."
            ),
            "metrics": [
                ("Vehicles", Vehicle.objects.filter(status="active").count()),
                ("Trips", Trip.objects.count()),
                ("Visible riders", assignments.count()),
            ],
            "sections": [
                {
                    "title": "Transport assignments",
                    "help": "Families see only currently linked children.",
                    "headings": ["Student", "Route", "Direction", "Pickup", "Drop-off"],
                    "rows": [
                        (
                            str(x.student),
                            x.trip.route.name,
                            x.trip.get_direction_display(),
                            x.pickup_stop.name,
                            x.dropoff_stop.name,
                        )
                        for x in assignments[:50]
                    ],
                }
            ],
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def assignment(request):
    if not request.user.has_perm("transport.manage_transport"):
        raise PermissionDenied
    form = AssignmentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            assign_student(request.user, form.save(commit=False))
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Student transport assignment saved.")
            return redirect("transport:overview")
    return render(
        request,
        "operations/phase7_form.html",
        {
            "title": "Assign student transport",
            "hint": "Capacity, route stops and current relationships are validated.",
            "form": form,
        },
    )
