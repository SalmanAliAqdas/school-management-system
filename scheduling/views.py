from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from attendance.calendar import school_now

from . import forms, selectors, services
from .access import children, require, selected_child
from .models import Entry, Period, Timetable


@login_required
def overview(request):
    today = school_now().date()
    child = selected_child(request)
    rows = selectors.tables(request.user).order_by("-starts_on")
    return render(
        request,
        "scheduling/overview.html",
        {
            "tables": rows,
            "today": today,
            "lessons": selectors.daily(request.user, today, child),
            "children": children(request.user),
            "selected_child": child,
            "active_nav": "timetable",
        },
    )


@login_required
def setup(request, kind):
    require(request.user, "scheduling.manage_timetable")
    if kind not in forms.SETUP:
        raise Http404
    form = forms.SETUP[kind](request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.save_setup(request.user, form.save(commit=False))
            return redirect("scheduling:setup", kind=kind)
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(
        request,
        "operations/phase7_form.html",
        {"form": form, "title": f"Timetable {kind}", "rows": form._meta.model.objects.all()[:100]},
    )


@login_required
def create(request, pk=None):
    require(request.user, "scheduling.manage_timetable")
    table = get_object_or_404(Timetable, pk=pk) if pk else None
    form = forms.TimetableForm(request.POST or None, instance=table)
    if request.method == "POST" and form.is_valid():
        try:
            table = services.save_table(request.user, form.save(commit=False))
            return redirect("scheduling:detail", pk=table.pk)
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(
        request, "operations/phase7_form.html", {"form": form, "title": "Timetable draft"}
    )


@login_required
def detail(request, pk):
    table = get_object_or_404(selectors.tables(request.user), pk=pk)
    child = selected_child(request)
    entries = selectors.lessons(request.user, child=child).filter(timetable=table)
    from types import SimpleNamespace

    shifts = entries.values_list("period__shift", flat=True).distinct()
    breaks = Period.objects.filter(academic_year=table.academic_year, shift__in=shifts).exclude(
        kind="lesson"
    )
    blocks = list(entries) + [SimpleNamespace(period=p, assignment=None) for p in breaks]
    report = (
        services.assistance(table) if request.user.has_perm("scheduling.manage_timetable") else None
    )
    return render(
        request,
        "scheduling/detail.html",
        {
            "table": table,
            "entries": entries,
            "days": [
                (
                    i,
                    label,
                    sorted(
                        [item for item in blocks if item.period.weekday == i],
                        key=lambda item: item.period.starts_at,
                    ),
                )
                for i, label in enumerate(
                    ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
                )
            ],
            "report": report,
            "periods": Period.objects.filter(academic_year=table.academic_year, kind="lesson"),
            "history": table.schedulehistory_set.all().order_by("-pk")[:20] if report else [],
            "active_nav": "timetable",
        },
    )


@login_required
def entry(request, pk, entry_id=None):
    require(request.user, "scheduling.manage_timetable")
    table = get_object_or_404(Timetable, pk=pk)
    row = (
        get_object_or_404(Entry, timetable=table, pk=entry_id)
        if entry_id
        else Entry(timetable=table)
    )
    form = forms.EntryForm(request.POST or None, instance=row)
    form.fields["period"].queryset = Period.objects.filter(
        academic_year=table.academic_year, kind="lesson"
    )
    form.fields["assignment"].queryset = form.fields["assignment"].queryset.filter(
        academic_year=table.academic_year
    )
    if request.method == "POST" and form.is_valid():
        try:
            services.save_entry(
                request.user, form.save(commit=False), int(request.POST.get("revision", 0))
            )
            return redirect("scheduling:detail", pk=pk)
        except (ValidationError, ValueError) as exc:
            form.add_error(None, exc if isinstance(exc, ValidationError) else "Invalid revision.")
    return render(
        request,
        "operations/phase7_form.html",
        {
            "form": form,
            "title": "Allocate lesson",
            "revision": table.revision,
            "hint": (
                "Choose an eligible teacher assignment and an active room. "
                "Server validation checks overlapping times, leave, breaks and employment."
            ),
        },
    )


@login_required
@require_POST
def action(request, pk, action):
    try:
        if action == "copy":
            table = services.copy_table(request.user, pk)
            return redirect("scheduling:detail", pk=table.pk)
        services.transition(request.user, pk, action)
        messages.success(request, "Timetable updated.")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect("scheduling:detail", pk=pk)


@login_required
def substitute(request, pk):
    require(request.user, "scheduling.manage_timetable")
    row = get_object_or_404(Entry, pk=pk)
    form = forms.SubstitutionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.substitute(
                request.user,
                row.pk,
                form.cleaned_data["date"],
                form.cleaned_data["teacher"],
                form.cleaned_data["reason"],
                form.cleaned_data["approve"],
            )
            return redirect("scheduling:detail", pk=row.timetable_id)
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(
        request, "operations/phase7_form.html", {"form": form, "title": "Teacher substitution"}
    )


@login_required
@require_POST
def remove(request, pk):
    row = get_object_or_404(Entry, pk=pk)
    table_id = row.timetable_id
    try:
        services.remove_entry(request.user, pk, int(request.POST.get("revision", 0)))
    except (ValidationError, ValueError) as exc:
        messages.error(request, str(exc))
    return redirect("scheduling:detail", pk=table_id)


@login_required
def reports(request):
    from academics.models import TeachingAssignment

    from .models import Booking, Substitution

    rows = selectors.tables(request.user)
    lessons = selectors.lessons(request.user)
    teacher_id = getattr(getattr(request.user, "teacher_profile", None), "pk", None)
    duties = Substitution.objects.filter(entry__timetable__in=rows).select_related(
        "teacher", "entry__assignment__teacher", "entry__period", "entry__assignment__section"
    )
    if not request.user.has_perm("scheduling.manage_timetable"):
        require(request.user, "accounts.access_teacher_dashboard")
        lessons = lessons.filter(assignment__teacher_id=teacher_id)
        duties = duties.filter(teacher_id=teacher_id)
    from django.db.models import Count

    workload = (
        lessons.values(
            "assignment__teacher__first_name", "assignment__teacher__last_name", "period__weekday"
        )
        .annotate(periods=Count("pk"))
        .order_by("assignment__teacher__first_name", "period__weekday")
    )
    rooms = (
        Booking.objects.filter(entry__in=lessons, active=True)
        .values("room__name")
        .annotate(lessons=Count("pk"))
        .order_by("room__name")
    )
    free = Period.objects.filter(academic_year__is_current=True, kind="lesson").exclude(
        pk__in=lessons.values("period_id")
    )
    return render(
        request,
        "scheduling/reports.html",
        {
            "workload": workload,
            "teaching_assignments": TeachingAssignment.all_objects.select_related(
                "teacher", "section", "subject"
            )
            if request.user.has_perm("scheduling.manage_timetable")
            else [],
            "rooms": rooms,
            "duties": duties.order_by("-date")[:100],
            "free": free,
            "active_nav": "timetable",
        },
    )


@login_required
def duty(request, pk):
    from django.db.models import Q

    from people.models import Enrollment

    from .models import Substitution

    require(request.user, "accounts.access_teacher_dashboard")
    today = school_now().date()
    row = get_object_or_404(
        Substitution.objects.select_related("entry__assignment", "teacher"),
        pk=pk,
        teacher__user=request.user,
        state="approved",
        date=today,
        entry__timetable__state="published",
    )
    if (
        not row.teacher.is_active
        or row.teacher.joined_on > today
        or (row.teacher.left_on and row.teacher.left_on < today)
    ):
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied
    roster = (
        Enrollment.objects.filter(
            academic_year=row.entry.assignment.academic_year,
            section=row.entry.assignment.section,
            started_on__lte=today,
        )
        .filter(Q(ended_on__isnull=True) | Q(ended_on__gte=today))
        .select_related("student")
    )
    return render(request, "scheduling/duty.html", {"duty": row, "roster": roster})


@login_required
def suggest(request, pk):
    require(request.user, "scheduling.manage_timetable")
    table = get_object_or_404(Timetable, pk=pk)
    period = get_object_or_404(
        Period, pk=request.GET.get("period"), academic_year=table.academic_year
    )
    return render(
        request,
        "scheduling/suggestions.html",
        {"table": table, "period": period, **services.suggestions(table, period)},
    )


@login_required
def assignment_access(request, pk):
    from django import forms as django_forms

    from academics.models import TeachingAssignment

    require(request.user, "academics.change_teachingassignment")
    row = get_object_or_404(TeachingAssignment.all_objects, pk=pk)

    class AccessForm(django_forms.Form):
        active = django_forms.BooleanField(required=False, label="Allow this teaching assignment")
        reason = django_forms.CharField(max_length=500, widget=django_forms.Textarea)

    form = AccessForm(request.POST or None, initial={"active": row.is_active})
    if request.method == "POST" and form.is_valid():
        services.assignment_access(request.user, pk, **form.cleaned_data)
        return redirect("scheduling:reports")
    return render(
        request,
        "operations/phase7_form.html",
        {"form": form, "title": "Teaching assignment access", "hint": str(row)},
    )
