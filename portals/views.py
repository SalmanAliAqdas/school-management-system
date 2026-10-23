from datetime import date

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Case, Count, F, IntegerField, Q, Value, When
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from academics.models import AcademicYear, ClassSubject, TeachingAssignment
from attendance.calendar import SchoolCalendar, school_now
from attendance.reporting import month_cells, report_rows, summary
from attendance.selectors import (
    leaves_visible_to,
    registers_visible_to,
    staff_entries_visible_to,
    student_entries_visible_to,
)
from audit.services import record_event
from core.context_processors import DASHBOARDS
from core.models import SchoolSettings
from examinations.reporting import current_results, published_subject_history
from examinations.selectors import results_visible_to
from finance.common import config
from finance.payments import invoice_total_map
from finance.selectors import (
    invoices_visible_to,
    payments_visible_to,
)
from people.models import Guardian, GuardianStudent, Staff, Teacher

from .forms import AccountPreferencesForm, SecurePasswordChangeForm
from .notifications import SOURCES, hydrate, inbox, mark_read
from .selectors import (
    ROLES,
    assignment_roster,
    assignment_writable,
    assignments,
    personal_finance_students,
    personal_students,
    require_role,
    student_years,
    teacher_sheets,
)
from .services import (
    attendance_trend,
    calendar_items,
    child_summaries,
    month_end,
    schedules_for,
)


def portal_render(request, template, context=None, *, status=200):
    school = SchoolSettings.objects.first()
    with timezone.override(school.timezone if school else "Asia/Karachi"):
        return render(request, f"portals/{template}.html", context, status=status)


def child_context(request, role, child_id):
    children = personal_students(request.user, role)
    child = get_object_or_404(children, pk=child_id)
    return {
        "portal_role": role,
        "role_label": ROLES[role][0],
        "selected_student": child,
        "children": children[:100],
        "finance_allowed": personal_finance_students(request.user, role)
        .filter(pk=child.pk)
        .exists(),
    }


def select_year(request, years):
    value = request.GET.get("academic_year")
    if value:
        if not value.isdigit() or len(value) > 9:
            raise Http404
        return get_object_or_404(years, pk=value)
    return years.filter(is_current=True).first() or years.first()


def teacher_context(request):
    rows = assignments(request.user)
    years = AcademicYear.objects.filter(teaching_assignments__in=rows).distinct()
    year = select_year(request, years)
    rows = rows.filter(academic_year=year) if year else rows.none()
    return {
        "portal_role": "teacher",
        "role_label": "Teaching",
        "years": years,
        "year": year,
        "assignments": rows,
    }


@login_required
@require_GET
def overview(request, role, legacy=None):
    require_role(request.user, role)
    today = school_now().date()
    year = AcademicYear.objects.filter(is_current=True).first()
    context = {
        **(legacy or {}),
        "portal_role": role,
        "role_label": ROLES[role][0],
        "today": today,
        "current_year": year,
        "active_nav": "overview",
    }
    if role == "teacher":
        context.update(teacher_context(request))
        work = list(
            context["assignments"]
            .annotate(
                student_total=Count(
                    "section__enrollments__student",
                    filter=Q(
                        section__enrollments__academic_year=context["year"],
                        section__enrollments__started_on__lte=today,
                    )
                    & (
                        Q(section__enrollments__ended_on__isnull=True)
                        | Q(section__enrollments__ended_on__gte=today)
                    ),
                    distinct=True,
                )
            )
            .order_by("section__school_class__sort_order", "section__name", "subject__name")[:40]
        )
        register_rows = registers_visible_to(request.user).filter(
            academic_year=context["year"],
            section_id__in=[a.section_id for a in work],
            attendance_on=today,
        )
        registers = {r.section_id: r for r in register_rows}
        calendar = SchoolCalendar(context["year"]) if context["year"] else None
        for item in work:
            item.register = registers.get(item.section_id)
            item.writable = assignment_writable(item, today)
            item.calendar_reason = calendar.reason(today) if calendar else "No academic year"
        sheets = teacher_sheets(request.user, context["assignments"])
        working_dates = (
            calendar.working_dates(today.replace(day=1), today, staff=True) if calendar else []
        )
        context.update(
            work=work,
            teacher=Teacher.objects.filter(user=request.user).first(),
            sheets=sheets.filter(state__in=["draft", "returned", "submitted", "review"])
            .annotate(
                entry_total=Count("assessment__exam_subject__cohort__candidates", distinct=True),
                completed_total=Count(
                    "entries", filter=~Q(entries__status="pending"), distinct=True
                ),
                action_priority=Case(
                    When(state="returned", then=Value(0)),
                    When(state="draft", then=Value(1)),
                    default=Value(2),
                    output_field=IntegerField(),
                ),
            )
            .order_by("action_priority", "pk")[:8],
            published_summaries=sheets.filter(
                assessment__exam_subject__cohort__session__state__in=["published", "archived"]
            )
            .order_by("-assessment__exam_subject__cohort__session__ends_on")
            .values(
                session_id=F("assessment__exam_subject__cohort__session_id"),
                session_name=F("assessment__exam_subject__cohort__session__name"),
                section_name=F("assessment__exam_subject__cohort__section__name"),
                class_name=F("assessment__exam_subject__cohort__section__school_class__name"),
                subject_name=F("assessment__exam_subject__subject__name"),
            )
            .distinct()[:6],
            recent_registers=registers_visible_to(request.user)
            .filter(
                academic_year=context["year"],
                section_id__in=[a.section_id for a in work],
                state="final",
            )
            .order_by("-submitted_at")[:6],
            staff_stats=summary(
                staff_entries_visible_to(request.user).filter(
                    teacher__user=request.user, attendance_on__in=working_dates
                ),
                staff=True,
            ),
            leaves=leaves_visible_to(request.user)
            .filter(teacher__user=request.user)
            .order_by("-starts_on")[:5],
            calendar=[
                item
                for item in calendar_items(request.user, context["year"], teacher=True)
                if item["date"] >= today
            ],
        )
        return portal_render(request, "teacher", context)
    children = personal_students(request.user, role)
    page = Paginator(children, 12).get_page(request.GET.get("page"))
    summaries = child_summaries(request.user, list(page), year, today, role=role)
    selected = summaries[0]["student"] if summaries and role == "student" else None
    context.update(
        children=children[:100],
        page_obj=page,
        summaries=summaries,
        selected_student=selected,
        finance_allowed=bool(summaries and summaries[0]["balance"] is not None),
        finance_settings=config(),
    )
    if request.GET.get("child"):
        try:
            selected = get_object_or_404(children, pk=request.GET["child"])
        except (ValueError, ValidationError) as exc:
            raise Http404 from exc
        context.update(child_context(request, role, selected.pk))
    context["recent_notices"] = hydrate(request.user, Paginator(inbox(request.user), 5).get_page(1))
    context["calendar"] = (
        calendar_items(request.user, year, student=selected, role=role) if selected else []
    )
    context["calendar"] = [item for item in context["calendar"] if item["date"] >= today]
    return portal_render(request, "overview", context)


@login_required
@require_GET
def student_page(request, role, child_id, section):
    if section not in ("profile", "attendance", "results", "reports", "fees", "calendar"):
        raise Http404
    context = child_context(request, role, child_id)
    capability = {
        "attendance": "attendance.view_attendance",
        "results": "examinations.view_examinations",
        "reports": "examinations.view_examinations",
    }.get(section)
    if capability and not request.user.has_perm(capability):
        raise PermissionDenied
    student = context["selected_student"]
    years = student_years(student)
    year = select_year(request, years)
    context.update(active_nav=section, years=years, year=year)
    placements = student.enrollments.select_related("academic_year", "section__school_class")
    if section == "profile":
        current = placements.filter(is_active=True).first()
        context.update(
            placements=placements,
            placement=current,
            guardians=GuardianStudent.objects.filter(student=student).select_related("guardian")
            if role == "student"
            else GuardianStudent.objects.filter(
                student=student, guardian__user=request.user
            ).select_related("guardian"),
            subjects=ClassSubject.objects.filter(
                academic_year=current.academic_year, school_class=current.section.school_class
            ).select_related("subject")
            if current
            else [],
            subject_teachers=TeachingAssignment.objects.filter(
                academic_year=current.academic_year,
                section=current.section,
                teacher__is_active=True,
            ).select_related("teacher", "subject")
            if current
            else [],
        )
    elif section == "attendance":
        day = school_now().date()
        try:
            day = (
                date.fromisoformat(request.GET["month"] + "-01")
                if request.GET.get("month")
                else day
            )
        except ValueError as exc:
            raise Http404 from exc
        if year:
            if not request.GET.get("month") and not year.starts_on <= day <= year.ends_on:
                day = year.starts_on
            data = {"academic_year": year, "date": day, "period": "month", "student": student}
            rows, start, end, calendar = report_rows(request.user, data)
            history = student_entries_visible_to(request.user).filter(
                student=student,
                register__academic_year=year,
                attendance_on__range=(day.replace(day=1), month_end(day)),
            )
            context.update(
                stats=summary(rows),
                month=day,
                cells=month_cells(
                    year, day, list(history), list(placements.filter(academic_year=year)), calendar
                ),
                page_obj=Paginator(history.order_by("-attendance_on", "pk"), 25).get_page(
                    request.GET.get("page")
                ),
                trend=attendance_trend(request.user, student, year),
                start=start,
                end=end,
            )
    elif section in ("results", "reports"):
        rows = (
            results_visible_to(request.user)
            if section == "reports"
            else current_results(request.user)
        )
        rows = rows.filter(candidate__student=student, candidate__withheld=False).exclude(
            data__outcome="withheld"
        )
        # Current withholding also suppresses every historical snapshot.
        withheld = (
            current_results(request.user)
            .filter(candidate__student=student, data__outcome="withheld")
            .values("candidate_id")
        )
        rows = rows.exclude(candidate_id__in=withheld)
        if year:
            rows = rows.filter(publication__session__academic_year=year)
        chart_rows = (
            current_results(request.user)
            .filter(
                candidate__student=student,
                candidate__withheld=False,
                data__outcome__in=["pass", "fail"],
            )
            .order_by("publication__session__ends_on")[:100]
        )
        context.update(
            page_obj=Paginator(rows.order_by("-publication__created_at", "pk"), 15).get_page(
                request.GET.get("page")
            ),
            progress=[
                {"label": row.data["session"], "percentage": row.data.get("percentage")}
                for row in chart_rows
            ],
            schedules=schedules_for(request.user, student).filter(starts_at__gte=school_now())[:12],
        )
    elif section == "fees":
        if not context["finance_allowed"]:
            raise PermissionDenied
        from finance.ledger import student_balances

        invoices = invoices_visible_to(request.user).filter(
            student=student, state__in=["issued", "voided"]
        )
        page = Paginator(invoices, 12).get_page(request.GET.get("page"))
        totals = invoice_total_map(list(page))
        context.update(
            page_obj=page,
            invoices=[{"invoice": row, "totals": totals[row.pk]} for row in page],
            balances=student_balances(student),
            finance_settings=config(),
            payments=payments_visible_to(request.user)
            .filter(student=student, state="posted")
            .order_by("-paid_on")[:30],
        )
    else:
        context["calendar"] = calendar_items(request.user, year, student=student, role=role)
    return portal_render(request, section, context)


@login_required
@require_GET
def classes(request):
    context = teacher_context(request)
    rows = context["assignments"]
    query = request.GET.get("q", "").strip()[:100]
    if query:
        rows = rows.filter(
            Q(section__school_class__name__icontains=query)
            | Q(subject__name__icontains=query)
            | Q(section__name__icontains=query)
        )
    context.update(
        active_nav="classes",
        query=query,
        page_obj=Paginator(rows.order_by("section__school_class__sort_order", "pk"), 15).get_page(
            request.GET.get("page")
        ),
    )
    return portal_render(request, "classes", context)


@login_required
@require_GET
def classroom(request, pk, student_id=None):
    assignment = get_object_or_404(assignments(request.user), pk=pk)
    historical = not assignment_writable(assignment)
    roster = assignment_roster(assignment, historical=historical)
    query = request.GET.get("q", "").strip()[:100]
    context = {
        "portal_role": "teacher",
        "role_label": "Teaching",
        "active_nav": "classes",
        "assignment": assignment,
        "writable": not historical,
        "today": school_now().date(),
        "query": query,
    }
    if student_id:
        placement = get_object_or_404(roster, student_id=student_id)
        context.update(
            student=placement.student,
            placement=placement,
            attendance=student_entries_visible_to(request.user)
            .filter(enrollment=placement, attendance_on__gte=assignment.teacher.joined_on)
            .filter(
                attendance_on__lte=assignment.teacher.left_on or assignment.academic_year.ends_on
            )
            .order_by("-attendance_on")[:30],
            subject_history=published_subject_history(request.user, assignment, placement.student),
        )
        return portal_render(request, "teacher_student", context)
    if query:
        roster = roster.filter(
            Q(student__first_name__icontains=query)
            | Q(student__last_name__icontains=query)
            | Q(student__admission_number__icontains=query)
        )
    context.update(
        page_obj=Paginator(roster, 30).get_page(request.GET.get("page")),
        sheets=teacher_sheets(request.user, assignments(request.user).filter(pk=pk)).order_by("pk")[
            :30
        ],
    )
    return portal_render(request, "classroom", context)


@login_required
@require_GET
def notification_inbox(request):
    category = request.GET.get("category", "")
    if category and category not in SOURCES:
        raise Http404
    child = None
    if request.GET.get("child"):
        from people.selectors import students_visible_to

        personal_scope = Q(pk__in=[])
        if request.user.has_perm("accounts.access_student_dashboard"):
            personal_scope |= Q(user=request.user)
        if request.user.has_perm("accounts.access_parent_dashboard"):
            personal_scope |= Q(guardian_links__guardian__user=request.user)
        try:
            child = get_object_or_404(
                students_visible_to(request.user).filter(personal_scope).distinct(),
                pk=request.GET["child"],
            )
        except (ValueError, ValidationError) as exc:
            raise Http404 from exc
    page = Paginator(
        inbox(
            request.user, category=category, unread=request.GET.get("unread") == "1", child=child
        ),
        20,
    ).get_page(request.GET.get("page"))
    return portal_render(
        request,
        "notifications",
        {
            "page_obj": hydrate(request.user, page),
            "active_nav": "notifications",
            "category": category,
            "child_filter": str(child.pk) if child else "",
        },
    )


@login_required
@require_POST
def notification_read(request, category, pk):
    if mark_read(request.user, category, pk):
        record_event("portal.notification_read", actor=request.user, target=f"{category}:{pk}")
    return redirect("portals:notifications")


@login_required
@require_GET
def select_child(request):
    children = personal_students(request.user, "parent")
    try:
        child = get_object_or_404(children, pk=request.GET.get("child", ""))
    except (ValueError, ValidationError) as exc:
        raise Http404 from exc
    section = request.GET.get("section", "profile")
    if section not in ("profile", "attendance", "results", "reports", "fees", "calendar"):
        section = "profile"
    return redirect("portals:student", role="parent", child_id=child.pk, section=section)


@login_required
@require_POST
def switch(request):
    role = request.POST.get("role")
    definition = next((d for d in DASHBOARDS if d[0] == role), None)
    if not definition or not request.user.has_perm(definition[2]):
        raise PermissionDenied
    request.session["selected_portal"] = role
    return redirect("core:role_dashboard", role=role)


@login_required
@require_http_methods(["GET", "POST"])
def settings(request):
    profiles = [
        profile
        for model in (Guardian, Teacher, Staff)
        if (profile := model.objects.filter(user=request.user).first())
    ]
    form = AccountPreferencesForm(
        request.POST or None,
        contact_profiles=profiles,
        initial={
            "phone": profiles[0].phone if profiles else "",
            "density": request.session.get("display_density", "comfortable"),
        },
    )
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            for profile in profiles:
                type(profile).objects.filter(pk=profile.pk, user=request.user).update(
                    phone=form.cleaned_data["phone"]
                )
            request.session["display_density"] = form.cleaned_data["density"]
            record_event("portal.preferences_updated", actor=request.user, target=request.user.pk)
        messages.success(request, "Your preferences have been saved.")
        return redirect("portals:settings")
    return portal_render(request, "settings", {"form": form, "active_nav": "settings"})


@login_required
@require_http_methods(["GET", "POST"])
def password_change(request):
    form = SecurePasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        record_event("account.password_changed", actor=user, target=user.pk)
        messages.success(request, "Your password has been changed.")
        return redirect("portals:settings")
    return portal_render(request, "password_change", {"form": form, "active_nav": "settings"})
