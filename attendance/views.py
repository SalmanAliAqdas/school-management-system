from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from academics.models import AcademicYear
from audit.services import record_event
from core.operations import form_errors, require_capability
from people.models import Staff, Teacher
from people.selectors import enrollments_visible_to, students_visible_to

from .calendar import SchoolCalendar, school_now
from .exports import MAX_EXPORT_ROWS, export_response
from .forms import (
    CalendarCancelForm,
    CalendarEventForm,
    CorrectionForm,
    DecisionForm,
    LeaveForm,
    PolicyForm,
    RegisterSaveForm,
    RegisterSelectionForm,
    ReportFilterForm,
    StaffRowSet,
    StudentRowSet,
)
from .models import AttendancePolicy, StaffAttendance, StaffRegister, StudentRegister
from .reporting import (
    class_summaries,
    daily_trends,
    department_summaries,
    month_cells,
    monthly_trends,
    report_rows,
    staff_summaries,
    student_summaries,
    summary,
)
from .selectors import (
    corrections_visible_to,
    enrollment_roster,
    leaves_visible_to,
    notifications_visible_to,
    registers_visible_to,
    staff_entries_visible_to,
    staff_roster,
    student_entries_visible_to,
)
from .services import (
    approved_leave_keys,
    cancel_calendar_event,
    decide_correction,
    decide_leave,
    request_correction,
    request_leave,
    save_calendar_event,
    save_policy,
    save_staff_register,
    save_student_register,
    snapshot,
)


def attendance_render(request, template, context=None, *, status=200):
    return render(
        request,
        template,
        {
            "active_nav": "attendance",
            "attendance_zone": str(school_now().tzinfo),
            **(context or {}),
        },
        status=status,
    )


def selected_year(request):
    value = request.GET.get("academic_year") or request.POST.get("academic_year")
    if value:
        from core.operations import positive_id

        return get_object_or_404(AcademicYear, pk=positive_id(value))
    return AcademicYear.objects.filter(is_current=True).first() or AcademicYear.objects.first()


def report_form(request, *, staff=False, compact=False, personal=False):
    year = selected_year(request)
    params = request.GET.copy()
    if year and not params.get("academic_year"):
        params["academic_year"] = str(year.pk)
    if not params.get("date"):
        params["date"] = school_now().date().isoformat()
    if not params.get("period"):
        params["period"] = "month"
    return ReportFilterForm(
        params, actor=request.user, staff=staff, compact=compact, personal=personal
    ), year


@login_required
@require_GET
def dashboard(request, staff=False):
    permission = "attendance.view_staff_attendance" if staff else "attendance.view_attendance"
    if (
        not staff
        and not request.user.has_perm(permission)
        and request.user.has_perm("attendance.view_staff_attendance")
    ):
        return redirect("attendance:staff_dashboard")
    require_capability(request.user, permission)
    form, year = report_form(request, staff=staff, compact=True)
    if not year or not form.is_valid():
        return attendance_render(
            request, "attendance/dashboard.html", {"form": form, "staff_mode": staff, "year": year}
        )
    data = {**form.cleaned_data, "period": "year", "status": ""}
    try:
        annual, _, _, calendar = report_rows(request.user, data, staff=staff)
    except ValidationError as exc:
        form_errors(form, exc)
        return attendance_render(
            request, "attendance/dashboard.html", {"form": form, "staff_mode": staff, "year": year}
        )
    day = form.cleaned_data.get("date") or school_now().date()
    today_rows = annual.filter(attendance_on=day)
    month_rows = annual.filter(attendance_on__year=day.year, attendance_on__month=day.month)
    comparisons = department_summaries(month_rows) if staff else class_summaries(month_rows)
    people = staff_summaries(month_rows) if staff else student_summaries(month_rows)
    policy = calendar.policy(day)
    threshold = policy.low_attendance_threshold if policy else Decimal("75")
    low = [row for row in people if row["percentage"] is not None and row["percentage"] < threshold]
    missing = []
    if (
        not staff
        and request.user.has_perm("attendance.mark_attendance")
        and not calendar.reason(day)
    ):
        roster = (
            enrollments_visible_to(request.user)
            .filter(academic_year=year, started_on__lte=day)
            .filter(Q(ended_on__isnull=True) | Q(ended_on__gte=day))
            .values("section_id", "section__name", "section__school_class__name")
            .annotate(total=Count("pk"))
        )
        submitted = dict(
            registers_visible_to(request.user)
            .filter(academic_year=year, attendance_on=day)
            .values_list("section_id", "state")
        )
        missing = [
            {**row, "state": submitted.get(row["section_id"], "missing")}
            for row in roster
            if submitted.get(row["section_id"]) != "final"
        ]
    staff_missing = (
        staff
        and request.user.has_perm("attendance.manage_staff_attendance")
        and not calendar.reason(day, staff=True)
        and not StaffRegister.objects.filter(
            academic_year=year, attendance_on=day, state="final"
        ).exists()
    )
    trend = daily_trends(
        annual.filter(attendance_on__gte=day - timedelta(days=30), attendance_on__lte=day),
        staff=staff,
    )
    months = monthly_trends(annual, staff=staff)
    chart = {
        "daily": [
            {
                "label": row["attendance_on"].isoformat(),
                "present": row["present"],
                "absent": row["absent"],
                "late": row["late"],
                "percentage": float(row["percentage"]) if row["percentage"] is not None else None,
            }
            for row in trend
        ],
        "monthly": [
            {
                "label": row["month"].strftime("%b %Y"),
                "percentage": float(row["percentage"]) if row["percentage"] is not None else None,
            }
            for row in months
        ],
    }
    return attendance_render(
        request,
        "attendance/dashboard.html",
        {
            "form": form,
            "year": year,
            "day": day,
            "policy": policy,
            "day_reason": calendar.reason(day, staff=staff),
            "stats": summary(today_rows, staff=staff),
            "monthly_stats": summary(month_rows, staff=staff),
            "comparisons": comparisons,
            "low": low,
            "threshold": threshold,
            "missing": missing,
            "staff_missing": staff_missing,
            "staff_mode": staff,
            "chart": chart,
            "children": students_visible_to(request.user)[:30],
            "staff_people": people,
            "trends": trend,
            "months": months,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def register(request, staff=False):
    require_capability(
        request.user,
        "attendance.manage_staff_attendance" if staff else "attendance.mark_attendance",
    )
    year = selected_year(request)
    defaults = {"academic_year": year.pk if year else None, "date": school_now().date()}
    data = request.POST if request.method == "POST" else request.GET or None
    selection = RegisterSelectionForm(data, initial=defaults, actor=request.user, staff=staff)
    rowset, save_form, roster_rows, saved, calendar_reason = None, None, [], None, ""
    if data and selection.is_valid():
        year, day = selection.cleaned_data["academic_year"], selection.cleaned_data["date"]
        calendar = SchoolCalendar(year)
        calendar_reason = calendar.reason(day, staff=staff)
        if staff:
            saved = StaffRegister.objects.filter(academic_year=year, attendance_on=day).first()
            roster = staff_roster(day)
            leave_keys = approved_leave_keys(day)
            existing = (
                {
                    entry.person_key: entry
                    for entry in saved.entries.select_related("teacher", "staff")
                }
                if saved
                else {}
            )
            initial = [
                {
                    "key": key,
                    **(
                        snapshot(existing[key])
                        if key in existing
                        else {
                            "status": "closure"
                            if calendar.is_closure(day)
                            else "leave"
                            if key in leave_keys
                            else ""
                        }
                    ),
                }
                for key, person in roster
            ]
            row_class = StaffRowSet
        else:
            section = selection.cleaned_data["section"]
            saved = StudentRegister.objects.filter(
                academic_year=year, section=section, attendance_on=day
            ).first()
            roster = [
                (str(enrollment.pk), enrollment)
                for enrollment in enrollment_roster(year, section, day)
            ]
            existing = (
                {
                    str(entry.enrollment_id): entry
                    for entry in saved.entries.select_related("student")
                }
                if saved
                else {}
            )
            initial = [
                {"key": key, **(snapshot(existing[key]) if key in existing else {})}
                for key, _person in roster
            ]
            row_class = StudentRowSet
        rowset = row_class(
            request.POST if request.method == "POST" else None, initial=initial, prefix="rows"
        )
        save_form = RegisterSaveForm(
            request.POST if request.method == "POST" else None,
            initial={"expected_version": saved.version if saved else 0, "action": "draft"},
        )
        if request.method == "POST" and rowset.is_valid() and save_form.is_valid():
            payload = {
                row["key"]: {key: value for key, value in row.items() if key != "key"}
                for row in rowset.cleaned_data
            }
            if len(payload) != len(rowset.cleaned_data):
                save_form.add_error(None, "Duplicate roster rows are not allowed.")
            else:
                try:
                    args = {
                        "year_id": year.pk,
                        "day": day,
                        "rows": payload,
                        "expected_version": save_form.cleaned_data["expected_version"],
                        "final": save_form.cleaned_data["action"] == "final",
                        "reason": save_form.cleaned_data["reason"],
                    }
                    if staff:
                        save_staff_register(request.user, **args)
                    else:
                        save_student_register(
                            request.user, section_id=selection.cleaned_data["section"].pk, **args
                        )
                except (ValidationError, IntegrityError) as exc:
                    form_errors(save_form, exc)
                else:
                    messages.success(
                        request,
                        "Attendance finalized." if args["final"] else "Attendance draft saved.",
                    )
                    url = reverse("attendance:staff_register" if staff else "attendance:register")
                    from urllib.parse import urlencode

                    params = {"academic_year": year.pk, "date": day.isoformat()}
                    if not staff:
                        params["section"] = selection.cleaned_data["section"].pk
                    return redirect(url + "?" + urlencode(params))
        for (key, person), form in zip(roster, rowset, strict=False):
            roster_rows.append(
                {
                    "key": key,
                    "person": person if staff else person.student,
                    "roll": "" if staff else person.roll_number,
                    "form": form,
                    "entry": existing.get(key),
                }
            )
    return attendance_render(
        request,
        "attendance/register.html",
        {
            "selection": selection,
            "rowset": rowset,
            "save_form": save_form,
            "rows": roster_rows,
            "saved": saved,
            "staff_mode": staff,
            "calendar_reason": calendar_reason,
        },
    )


@login_required
@require_GET
def student_detail(request, pk):
    require_capability(request.user, "attendance.view_attendance")
    student = get_object_or_404(students_visible_to(request.user), pk=pk)
    form, year = report_form(request, personal=True)
    context = {"student": student, "form": form, "year": year}
    if year and form.is_valid():
        data = {**form.cleaned_data, "student": student, "status": ""}
        try:
            rows, start, end, calendar = report_rows(request.user, data)
        except ValidationError as exc:
            form_errors(form, exc)
        else:
            month = data.get("date") or school_now().date()
            first, last = month.replace(day=1), month.replace(day=28) + timedelta(days=4)
            last = last.replace(day=1) - timedelta(days=1)
            history = student_entries_visible_to(request.user).filter(
                student=student, register__academic_year=year
            )
            placements = list(
                enrollments_visible_to(request.user).filter(student=student, academic_year=year)
            )
            context.update(
                stats=summary(rows),
                page_obj=Paginator(rows.order_by("-attendance_on", "pk"), 25).get_page(
                    request.GET.get("page")
                ),
                cells=month_cells(
                    year,
                    month,
                    history.filter(attendance_on__range=(first, last)),
                    placements,
                    calendar,
                ),
                month=month,
                start=start,
                end=end,
                corrections=corrections_visible_to(request.user).filter(
                    student_entry__student=student
                )
                if request.user.has_perm("attendance.request_correction")
                else [],
            )
    record_event("attendance.student_viewed", actor=request.user, target=pk)
    return attendance_render(request, "attendance/student_detail.html", context)


@login_required
@require_GET
def staff_detail(request, kind, pk):
    require_capability(request.user, "attendance.view_staff_attendance")
    model = {"teacher": Teacher, "staff": Staff}.get(kind)
    if not model:
        raise Http404
    scope = (
        model.objects.all()
        if request.user.has_perm("attendance.view_all_staff_attendance")
        else model.objects.filter(user=request.user)
    )
    person = get_object_or_404(scope, pk=pk)
    form, year = report_form(request, staff=True, personal=True)
    context = {
        "person": person,
        "person_kind": kind,
        "employee_key": f"{kind}:{person.pk}",
        "form": form,
        "year": year,
        "staff_mode": True,
    }
    if year and form.is_valid():
        try:
            rows, start, end, calendar = report_rows(request.user, form.cleaned_data, staff=True)
        except ValidationError as exc:
            form_errors(form, exc)
        else:
            rows = rows.filter(**{kind: person})
            month = form.cleaned_data.get("date") or school_now().date()
            first = month.replace(day=1)
            last = (month.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
            raw = staff_entries_visible_to(request.user).filter(
                **{kind: person}, register__academic_year=year, attendance_on__range=(first, last)
            )
            context.update(
                stats=summary(rows, staff=True),
                page_obj=Paginator(rows.order_by("-attendance_on", "pk"), 25).get_page(
                    request.GET.get("page")
                ),
                cells=month_cells(year, month, raw, [], calendar, staff=True, person=person),
                month=month,
                start=start,
                end=end,
                leaves=leaves_visible_to(request.user).filter(**{kind: person}),
                history=raw,
            )
    return attendance_render(request, "attendance/staff_detail.html", context)


REPORT_KINDS = {
    "students": "Student attendance",
    "summary": "Student attendance summary",
    "classes": "Class attendance comparison",
    "low": "Low student attendance",
    "staff": "Staff attendance",
    "staff-summary": "Teacher and staff summary",
    "departments": "Department attendance",
    "staff-absences": "Staff absence report",
}


@login_required
@require_GET
def reports(request, kind="students"):
    if kind not in REPORT_KINDS:
        raise Http404
    staff = kind.startswith("staff") or kind == "departments"
    require_capability(
        request.user, "attendance.view_staff_attendance" if staff else "attendance.view_attendance"
    )
    form, year = report_form(request, staff=staff)
    context = {
        "form": form,
        "year": year,
        "kind": kind,
        "title": REPORT_KINDS[kind],
        "staff_mode": staff,
        "report_kinds": REPORT_KINDS,
    }
    if not year or not form.is_valid():
        return attendance_render(
            request,
            "attendance/reports.html",
            context,
            status=400 if request.GET.get("format") else 200,
        )
    data = form.cleaned_data.copy()
    if kind in {"low", "summary", "classes", "staff-summary", "departments"}:
        data["status"] = ""
    if kind == "staff-absences":
        data["status"] = "absent"
    try:
        rows, start, end, calendar = report_rows(request.user, data, staff=staff)
        stats = summary(rows, staff=staff)
        headers, result = [], []
        if kind in {"summary", "low"}:
            groups = student_summaries(rows)
            threshold = (
                calendar.policy(end).low_attendance_threshold
                if calendar.policy(end)
                else Decimal(75)
            )
            if kind == "low":
                groups = [
                    row
                    for row in groups
                    if row["percentage"] is not None and row["percentage"] < threshold
                ]
            if data.get("sort") == "percentage" or kind == "low":
                groups.sort(
                    key=lambda row: (
                        row["percentage"] if row["percentage"] is not None else Decimal(101)
                    )
                )
            headers = [
                "Admission",
                "Student",
                "Present",
                "Absent",
                "Late",
                "Excused",
                "Attendance %",
            ]
            result = [
                [
                    row["student__admission_number"],
                    f"{row['student__first_name']} {row['student__last_name']}",
                    row["present"],
                    row["absent"],
                    row["late"],
                    row["excused"],
                    row["percentage"],
                ]
                for row in groups
            ]
        elif kind == "classes":
            headers = [
                "Class / section",
                "Recorded",
                "Present",
                "Absent",
                "Late",
                "Excused",
                "Attendance %",
            ]
            result = [
                [
                    f"{row['register__section__school_class__name']} · "
                    f"{row['register__section__name']}",
                    row["total"],
                    row["present"],
                    row["absent"],
                    row["late"],
                    row["excused"],
                    row["percentage"],
                ]
                for row in class_summaries(rows)
            ]
        elif kind in {"staff-summary", "departments"}:
            groups = (
                staff_summaries(rows) if kind == "staff-summary" else department_summaries(rows)
            )
            headers = [
                "Employee / department",
                "Present",
                "Absent",
                "Late",
                "Half-day",
                "Leave",
                "Duty",
                "Attendance %",
            ]
            result = [
                [
                    f"{row['first_name']} {row['last_name']} · {row['department']}"
                    if kind == "staff-summary"
                    else row["department_name"],
                    row["present"],
                    row["absent"],
                    row["late"],
                    row["half_day"],
                    row["leave"],
                    row["duty"],
                    row["percentage"],
                ]
                for row in groups
            ]
        else:
            order = (
                ["teacher__first_name", "staff__first_name", "-attendance_on", "pk"]
                if staff and data.get("sort") == "name"
                else ["student__first_name", "-attendance_on", "pk"]
                if data.get("sort") == "name"
                else ["-attendance_on", "pk"]
            )
            rows = rows.order_by(*order)
            headers = (
                ["Date", "Employee", "Department", "Status", "Arrival"]
                if staff
                else ["Date", "Admission", "Student", "Class / section", "Status", "Arrival"]
            )
            format_kind = request.GET.get("format")
            selected_rows = (
                list(rows[: MAX_EXPORT_ROWS + 1])
                if format_kind in {"csv", "pdf", "print"}
                else Paginator(rows, 30).get_page(request.GET.get("page"))
            )
            for row in selected_rows:
                result.append(
                    [
                        row.attendance_on,
                        str(row.person),
                        row.person.department,
                        row.get_status_display(),
                        row.arrival_time or "",
                    ]
                    if staff
                    else [
                        row.attendance_on,
                        row.student.admission_number,
                        str(row.student),
                        str(row.register.section),
                        row.get_status_display(),
                        row.arrival_time or "",
                    ]
                )
            if format_kind not in {"csv", "pdf", "print"}:
                context["page_obj"] = selected_rows
        if request.GET.get("format") in {"csv", "pdf"}:
            return export_response(
                request.user,
                title=REPORT_KINDS[kind],
                headers=headers,
                rows=result,
                kind=request.GET["format"],
                period=f"{year} · {start} to {end}",
            )
        if request.GET.get("format") == "print" and len(result) > MAX_EXPORT_ROWS:
            raise ValidationError("Print at most 5,000 rows. Narrow the report filters.")
        if "page_obj" not in context and request.GET.get("format") != "print":
            page = Paginator(result, 30).get_page(request.GET.get("page"))
            context["page_obj"], result = page, list(page)
        context.update(headers=headers, rows=result, stats=stats, start=start, end=end)
    except ValidationError as exc:
        form_errors(form, exc)
        return attendance_render(request, "attendance/reports.html", context, status=400)
    return attendance_render(
        request,
        "attendance/print_report.html"
        if request.GET.get("format") == "print"
        else "attendance/reports.html",
        context,
    )


@login_required
@require_http_methods(["GET", "POST"])
def calendar_cancel(request, pk):
    require_capability(request.user, "attendance.manage_policy")
    from .models import CalendarEvent

    event = get_object_or_404(CalendarEvent, pk=pk)
    form = CalendarCancelForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            cancel_calendar_event(request.user, pk, form.cleaned_data["reason"])
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(request, "Calendar exception cancelled. Its history is retained.")
            return redirect("attendance:settings")
    return render(
        request,
        "operations/form.html",
        {
            "form": form,
            "title": f"Cancel calendar exception: {event.title}",
            "description": "This changes which dates count as working days. Existing attendance "
            "records are retained; review corrections for any previously recorded closure rows.",
            "back_url": "attendance:settings",
            "active_nav": "attendance",
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def policy_edit(request, pk=None):
    require_capability(request.user, "attendance.manage_policy")
    obj = get_object_or_404(AttendancePolicy, pk=pk) if pk else None
    form = PolicyForm(request.POST if request.method == "POST" else None, instance=obj)
    if request.method == "POST" and form.is_valid():
        try:
            save_policy(request.user, form)
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(request, "Attendance policy saved.")
            return redirect("attendance:settings")
    return render(
        request,
        "operations/form.html",
        {
            "form": form,
            "title": "Attendance policy revision",
            "description": "Late credit is between 0 and 1. "
            "Excused exclusions affect the denominator. "
            "A policy used by a register is protected.",
            "back_url": "attendance:settings",
            "active_nav": "attendance",
        },
    )


@login_required
@require_GET
def settings_view(request):
    require_capability(request.user, "attendance.manage_policy")
    from .models import CalendarEvent

    return attendance_render(
        request,
        "attendance/settings.html",
        {
            "policies": AttendancePolicy.objects.select_related("academic_year"),
            "events": CalendarEvent.objects.select_related("academic_year"),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def calendar_create(request):
    require_capability(request.user, "attendance.manage_policy")
    form = CalendarEventForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            save_calendar_event(request.user, form)
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(
                request,
                "Calendar exception saved. Records on excluded days remain in history "
                "and do not affect percentages.",
            )
            return redirect("attendance:settings")
    return render(
        request,
        "operations/form.html",
        {
            "form": form,
            "title": "School calendar exception",
            "description": "Holidays and closures exclude days from calculations. "
            "Existing finalized records are retained. "
            "A working-day exception cannot override a holiday or closure.",
            "back_url": "attendance:settings",
            "active_nav": "attendance",
        },
    )


@login_required
@require_GET
def correction_list(request):
    if not any(
        request.user.has_perm(perm)
        for perm in [
            "attendance.request_correction",
            "attendance.request_staff_correction",
            "attendance.approve_correction",
            "attendance.approve_staff_correction",
        ]
    ):
        raise PermissionDenied
    rows = corrections_visible_to(request.user)
    if request.GET.get("state") in {"pending", "approved", "rejected"}:
        rows = rows.filter(state=request.GET["state"])
    return attendance_render(
        request,
        "attendance/corrections.html",
        {"page_obj": Paginator(rows, 25).get_page(request.GET.get("page"))},
    )


@login_required
@require_http_methods(["GET", "POST"])
def correction_create(request, kind, pk):
    if kind not in {"student", "staff"}:
        raise Http404
    require_capability(
        request.user,
        "attendance.request_staff_correction"
        if kind == "staff"
        else "attendance.request_correction",
    )
    source = (
        staff_entries_visible_to(request.user)
        if kind == "staff"
        else student_entries_visible_to(request.user)
    )
    entry = get_object_or_404(source, pk=pk)
    form = CorrectionForm(
        request.POST if request.method == "POST" else None,
        staff=kind == "staff",
        initial=snapshot(entry),
    )
    if request.method == "POST" and form.is_valid():
        try:
            request_correction(
                request.user,
                kind=kind,
                entry_id=pk,
                values={key: value for key, value in form.cleaned_data.items() if key != "reason"},
                reason=form.cleaned_data["reason"],
            )
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(
                request,
                "Correction requested. The finalized value remains unchanged until approval.",
            )
            return redirect("attendance:corrections")
    return attendance_render(
        request,
        "attendance/decision.html",
        {
            "form": form,
            "title": "Request attendance correction",
            "entry": entry,
            "original": snapshot(entry),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def correction_decide(request, pk):
    correction = get_object_or_404(corrections_visible_to(request.user), pk=pk)
    require_capability(
        request.user,
        "attendance.approve_staff_correction"
        if correction.staff_entry_id
        else "attendance.approve_correction",
    )
    form = DecisionForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            decide_correction(
                request.user,
                pk,
                approve=form.cleaned_data["decision"] == "approve",
                reason=form.cleaned_data["reason"],
            )
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(request, "Correction decision recorded.")
            return redirect("attendance:corrections")
    return attendance_render(
        request,
        "attendance/decision.html",
        {
            "form": form,
            "title": "Review attendance correction",
            "correction": correction,
            "entry": correction.entry,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def leave_create(request):
    require_capability(request.user, "attendance.request_leave")
    form = LeaveForm(request.POST if request.method == "POST" else None, actor=request.user)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            request_leave(
                request.user,
                year_id=data["academic_year"].pk,
                person=form.people[data["person"]],
                starts_on=data["starts_on"],
                ends_on=data["ends_on"],
                kind=data["kind"],
                reason=data["reason"],
            )
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(request, "Leave requested.")
            return redirect("attendance:leaves")
    return render(
        request,
        "operations/form.html",
        {
            "form": form,
            "title": "Request leave",
            "back_url": "attendance:leaves",
            "active_nav": "attendance",
        },
    )


@login_required
@require_GET
def leave_list(request):
    require_capability(request.user, "attendance.view_staff_attendance")
    rows = leaves_visible_to(request.user)
    if request.GET.get("state") in {"pending", "approved", "rejected"}:
        rows = rows.filter(state=request.GET["state"])
    return attendance_render(
        request,
        "attendance/leaves.html",
        {"page_obj": Paginator(rows, 25).get_page(request.GET.get("page"))},
    )


@login_required
@require_http_methods(["GET", "POST"])
def leave_decide(request, pk):
    require_capability(request.user, "attendance.approve_leave")
    leave = get_object_or_404(leaves_visible_to(request.user), pk=pk)
    form = DecisionForm(request.POST if request.method == "POST" else None)
    affected = StaffAttendance.objects.filter(
        **({"teacher_id": leave.teacher_id} if leave.teacher_id else {"staff_id": leave.staff_id}),
        attendance_on__range=(leave.starts_on, leave.ends_on),
    ).exclude(status__in=["closure", "leave"])
    if request.method == "POST" and form.is_valid():
        try:
            decide_leave(
                request.user,
                pk,
                approve=form.cleaned_data["decision"] == "approve",
                reason=form.cleaned_data["reason"],
            )
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(
                request,
                "Leave decision recorded with attendance correction history where applicable.",
            )
            return redirect("attendance:leaves")
    return attendance_render(
        request,
        "attendance/decision.html",
        {
            "form": form,
            "title": "Review leave request",
            "leave": leave,
            "affected_count": affected.count(),
        },
    )


@login_required
@require_GET
def notifications(request):
    require_capability(request.user, "attendance.view_attendance")
    page = Paginator(notifications_visible_to(request.user), 25).get_page(request.GET.get("page"))
    calendars = {}
    for notice in page:
        year = notice.entry.register.academic_year
        if year.pk not in calendars:
            calendars[year.pk] = SchoolCalendar(year)
        notice.exclusion_reason = calendars[year.pk].reason(notice.entry.attendance_on)
    return attendance_render(
        request,
        "attendance/notifications.html",
        {"page_obj": page},
    )


@login_required
@require_POST
def notification_read(request, pk):
    row = get_object_or_404(notifications_visible_to(request.user), pk=pk)
    from django.utils import timezone

    if not row.read_at:
        changed = (
            notifications_visible_to(request.user)
            .filter(pk=row.pk, read_at__isnull=True)
            .update(read_at=timezone.now(), updated_at=timezone.now())
        )
        if changed:
            record_event("attendance.notification_read", actor=request.user, target=row.pk)
    return redirect("attendance:notifications")
