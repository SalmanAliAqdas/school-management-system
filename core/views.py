from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, connection, transaction
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from academics.models import AcademicYear, TeachingAssignment
from audit.models import AuditEvent
from audit.services import record_event
from people.models import GuardianStudent
from people.selectors import enrollments_visible_to, students_visible_to

from .context_processors import DASHBOARDS
from .forms import SchoolSettingsForm
from .models import SchoolSettings
from .modules import MODULES
from .uploads import image_write

DASHBOARD_COPY = {
    "admin": (
        "Your school, at a glance.",
        "A clear view of your school community and what comes next.",
    ),
    "teacher": (
        "A good day to inspire.",
        "Your assigned classes and students, together in one place.",
    ),
    "student": (
        "Make room for possibility.",
        "Your school profile and academic journey start here.",
    ),
    "parent": (
        "Closer to their school day.",
        "A dedicated space for the children connected to your account.",
    ),
}


@require_GET
@never_cache
def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})


@login_required
def dashboard_redirect(request):
    selected = request.session.get("selected_portal")
    for key, _label, permission in DASHBOARDS:
        if key == selected and request.user.has_perm(permission):
            return redirect("core:role_dashboard", role=key)
    for key, _label, permission in DASHBOARDS:
        if request.user.has_perm(permission):
            return redirect("core:role_dashboard", role=key)
    if request.user.has_perm("finance.access_finance"):
        return redirect("finance:dashboard")
    return render(request, "core/no_access.html", status=403)


@login_required
@require_GET
def role_dashboard(request, role):
    definition = next((item for item in DASHBOARDS if item[0] == role), None)
    if not definition:
        raise Http404
    if not request.user.has_perm(definition[2]):
        raise PermissionDenied
    students = students_visible_to(request.user)
    enrollments = enrollments_visible_to(request.user)
    current_year = AcademicYear.objects.filter(is_current=True).first()
    enrolled = (
        enrollments.filter(academic_year=current_year, is_active=True).count()
        if current_year
        else 0
    )
    if role == "teacher":
        count_label = "Assigned subjects"
        count = (
            TeachingAssignment.objects.filter(
                teacher__user=request.user, academic_year=current_year
            ).count()
            if current_year
            else 0
        )
    elif role == "parent":
        count_label = "Linked children"
        count = GuardianStudent.objects.filter(guardian__user=request.user).count()
    else:
        count_label = "Current placements"
        count = enrolled
    chart_data = []
    if request.user.has_perm("people.view_student") and current_year:
        from django.db.models import Count

        chart_data = list(
            enrollments.filter(academic_year=current_year, is_active=True)
            .values("section__school_class__name")
            .annotate(total=Count("student", distinct=True))
            .order_by("section__school_class__sort_order")
        )
    title, subtitle = DASHBOARD_COPY[role]
    context = {
        "role": role,
        "role_label": definition[1],
        "headline": title,
        "subtitle": subtitle,
        "current_year": current_year,
        "student_count": students.count(),
        "secondary_count": count,
        "secondary_label": count_label,
        "recent_students": students[:5],
        "chart_data": chart_data,
        "active_nav": "dashboard",
        "module_previews": MODULES[:4],
    }
    if role != "admin":
        from portals.views import overview

        return overview(request, role, legacy=context)
    return render(
        request,
        "core/dashboard.html",
        context,
    )


@login_required
@require_GET
def roadmap(request):
    return render(request, "core/roadmap.html", {"modules": MODULES, "active_nav": "roadmap"})


@login_required
@require_GET
def module_detail(request, slug):
    module = next((item for item in MODULES if item["slug"] == slug), None)
    if not module:
        raise Http404
    if slug in ("homework", "timetable", "announcements"):
        return redirect(
            {
                "homework": "learning:overview",
                "timetable": "scheduling:overview",
                "announcements": "communications:overview",
            }[slug]
        )
    destinations = {
        "finance": ("finance.access_finance", "finance:dashboard", {}),
        "examinations": ("examinations.view_examinations", "examinations:dashboard", {}),
        "attendance": ("attendance.view_attendance", "attendance:dashboard", {}),
        "academics": ("academics.view_academicyear", "academics:overview", {}),
        "admissions": ("people.add_student", "people:admission", {}),
        "guardians": ("people.view_guardian", "people:directory", {"kind": "guardians"}),
        "staff": ("people.view_teacher", "people:directory", {"kind": "teachers"}),
    }
    if slug in destinations:
        permission, route, kwargs = destinations[slug]
        if request.user.has_perm(permission):
            if slug != "admissions" or request.user.has_perms(
                ["people.view_student", "people.view_all_students"]
            ):
                return redirect(route, **kwargs)
    if slug == "attendance" and request.user.has_perm("attendance.view_staff_attendance"):
        return redirect("attendance:staff_dashboard")
    return render(request, "core/module.html", {"module": module, "active_nav": slug})


@login_required
@permission_required("core.change_schoolsettings", raise_exception=True)
@require_http_methods(["GET", "POST"])
def school_settings(request):
    instance = SchoolSettings.objects.first()
    form = SchoolSettingsForm(
        request.POST if request.method == "POST" else None, request.FILES or None, instance=instance
    )
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            school = form.save(commit=False)
            with image_write(school, "logo"):
                school.save()
                record_event("school.settings_changed", actor=request.user, target=school.pk)
        messages.success(request, "School settings saved.")
        return redirect("core:school_settings")
    return render(request, "core/settings.html", {"form": form, "active_nav": "settings"})


@login_required
@require_GET
def school_logo(request):
    school = SchoolSettings.objects.first()
    if not school or not school.logo:
        raise Http404
    try:
        response = FileResponse(school.logo.open("rb"), content_type="image/png")
    except FileNotFoundError as exc:
        raise Http404 from exc
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_GET
def profile(request):
    return render(
        request,
        "core/profile.html",
        {"roles": request.user.groups.order_by("name"), "active_nav": "profile"},
    )


@login_required
@permission_required("audit.view_auditevent", raise_exception=True)
@require_GET
def audit_log(request):
    from django.core.paginator import Paginator

    events = AuditEvent.objects.select_related("actor")
    return render(
        request,
        "core/audit.html",
        {
            "page_obj": Paginator(events, 30).get_page(request.GET.get("page")),
            "active_nav": "audit",
        },
    )
