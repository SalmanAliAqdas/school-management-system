import base64
import csv
from io import StringIO

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Count, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from attendance.exports import safe_csv
from audit.services import record_event
from core.form_mixins import StyledFormMixin
from core.operations import form_errors

from .calculations import calculate_candidate
from .exports import report_pdf
from .forms import (
    SETUP,
    ActionForm,
    AmendmentForm,
    CandidateForm,
    CorrectionDecisionForm,
    CorrectionForm,
    MarkRows,
    MarksActionForm,
    RecommendationForm,
    ReviewForm,
    ScheduleForm,
    setup_form,
)
from .models import (
    ExamCandidate,
    ExaminationSettings,
    ExamSchedule,
    ExamSession,
    MarkEntry,
)
from .reporting import MAX_RESULTS, analytics, current_results
from .selectors import (
    amendments_visible_to,
    can_oversee,
    candidates_visible_to,
    capable,
    corrections_visible_to,
    notifications_visible_to,
    personal_students,
    results_visible_to,
    sessions_visible_to,
    sheets_visible_to,
    subjects_visible_to,
)
from .services import (
    decide_amendment,
    decide_correction,
    delete_setup,
    override_recommendation,
    request_amendment,
    request_correction,
    require,
    review_sheet,
    save_marks,
    save_schedule,
    save_setup,
    school_zone,
    session_action,
    setup_session_for,
    update_candidate,
)


def exam_render(request, template, context=None, status=200):
    response = render(
        request,
        f"examinations/{template}.html",
        {"active_nav": "examinations", "exam_zone": str(school_zone()), **(context or {})},
        status=status,
    )
    response["Cache-Control"] = "private, no-store"
    return response


def ensure_access(user):
    require(user, "view_examinations")


class ResultFilters(StyledFormMixin, forms.Form):
    session = forms.ModelChoiceField(queryset=ExamSession.objects.none(), required=False)
    query = forms.CharField(max_length=100, required=False, label="Search name or admission number")
    outcome = forms.ChoiceField(
        required=False,
        choices=[
            ("", "All outcomes"),
            ("pass", "Pass"),
            ("fail", "Fail"),
            ("incomplete", "Incomplete"),
            ("withheld", "Withheld"),
        ],
    )
    sort = forms.ChoiceField(
        required=False,
        choices=[
            ("student", "Student name"),
            ("-percentage", "Percentage: high first"),
            ("percentage", "Percentage: low first"),
        ],
    )

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["session"].queryset = sessions_visible_to(actor)


@login_required
@require_GET
def dashboard(request):
    ensure_access(request.user)
    sessions = sessions_visible_to(request.user)
    query, state = request.GET.get("q", "")[:100], request.GET.get("state", "")
    if query:
        sessions = sessions.filter(
            Q(name__icontains=query) | Q(academic_year__name__icontains=query)
        )
    if state in ExamSession.State.values:
        sessions = sessions.filter(state=state)
    ordering = request.GET.get("sort", "-starts_on")
    if ordering not in ("-starts_on", "starts_on", "name", "state"):
        ordering = "-starts_on"
    sessions = sessions.annotate(
        sheet_count=Count("cohorts__subjects__assessments__sheet", distinct=True),
        approved_count=Count(
            "cohorts__subjects__assessments__sheet",
            filter=Q(cohorts__subjects__assessments__sheet__state="approved"),
            distinct=True,
        ),
    ).order_by(ordering, "pk")
    results = current_results(request.user).order_by(
        "-publication__created_at", "candidate__student__first_name"
    )[:8]
    children = personal_students(request.user)
    child = None
    if request.GET.get("child"):
        try:
            child = get_object_or_404(children, pk=request.GET["child"])
        except (ValidationError, ValueError) as exc:
            raise Http404 from exc
    else:
        child = children.first()
    personal_chart = []
    if child:
        history = (
            current_results(request.user)
            .filter(candidate__student=child)
            .order_by("publication__session__ends_on", "publication__created_at")
        )
        personal_chart = [
            {"label": r.data["session"], "percentage": r.data["percentage"]}
            for r in history
            if r.data["percentage"] is not None
        ]
    return exam_render(
        request,
        "dashboard",
        {
            "page_obj": Paginator(sessions, 15).get_page(request.GET.get("page")),
            "query": query,
            "state": state,
            "states": ExamSession.State.choices,
            "results": results,
            "personal_chart": personal_chart,
            "children": children,
            "selected_child": child,
            "counts": sessions_visible_to(request.user).values("state").annotate(total=Count("pk")),
        },
    )


@login_required
@require_GET
def setup(request, kind):
    require(request.user, "manage_examinations")
    if kind not in SETUP:
        raise Http404
    model, title, fields = SETUP[kind]
    rows = model.objects.all()
    if kind == "sessions":
        rows = sessions_visible_to(request.user)
    elif kind in ("cohorts", "controllers", "sources"):
        rows = rows.filter(session__in=sessions_visible_to(request.user))
    elif kind == "subjects":
        rows = rows.filter(cohort__session__in=sessions_visible_to(request.user))
    elif kind == "assessments":
        rows = rows.filter(exam_subject__cohort__session__in=sessions_visible_to(request.user))
    labels = [model._meta.get_field(f).verbose_name.title() for f in fields]
    page = Paginator(rows.order_by("-pk"), 20).get_page(request.GET.get("page"))
    data = [{"object": row, "cells": [getattr(row, field) for field in fields]} for row in page]
    return exam_render(
        request,
        "setup",
        {
            "kind": kind,
            "title": title,
            "labels": labels,
            "rows": data,
            "page_obj": page,
            "setup_items": SETUP.items(),
        },
    )


def setup_object(user, kind, pk):
    model = SETUP[kind][0]
    try:
        instance = get_object_or_404(model, pk=model._meta.pk.to_python(pk))
    except (ValidationError, ValueError, TypeError) as exc:
        raise Http404 from exc
    session = setup_session_for(instance)
    if session and not can_oversee(user, session):
        raise Http404
    return instance


@login_required
@require_http_methods(["GET", "POST"])
def setup_edit(request, kind, pk=None):
    require(request.user, "manage_examinations")
    if kind not in SETUP:
        raise Http404
    instance = setup_object(request.user, kind, pk) if pk else None
    if kind == "settings":
        instance = ExaminationSettings.objects.first() or ExaminationSettings(pk=1)
    form = setup_form(kind)(
        request.POST or None,
        instance=instance,
        actor=request.user,
        initial={key: value for key, value in request.GET.items() if key in SETUP[kind][2]},
    )
    if request.method == "POST" and form.is_valid():
        try:
            saved = save_setup(request.user, form.save(commit=False))
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(request, "Examination configuration saved.")
            if kind == "sessions":
                return redirect("examinations:session", session_id=saved.pk)
            return redirect("examinations:setup", kind=kind)
    return exam_render(
        request,
        "form",
        {
            "form": form,
            "title": f"{'Edit' if pk else 'Add'} {SETUP[kind][1].lower()}",
            "description": (
                "Used configurations are protected. Create a new policy or session "
                "to change historical rules."
            ),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def setup_remove(request, kind, pk):
    require(request.user, "manage_examinations")
    if kind not in ("bands", "cohorts", "subjects", "assessments", "controllers", "sources"):
        raise Http404
    instance = setup_object(request.user, kind, pk)
    form = ActionForm(request.POST or None, initial={"expected_version": 0})
    if request.method == "POST" and form.is_valid():
        try:
            delete_setup(request.user, instance)
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(request, "Unused configuration removed.")
            return redirect("examinations:setup", kind=kind)
    return exam_render(
        request,
        "form",
        {
            "form": form,
            "title": "Remove unused configuration",
            "description": str(instance),
            "confirmation": True,
        },
    )


@login_required
@require_GET
def session_detail(request, session_id):
    session = get_object_or_404(sessions_visible_to(request.user), pk=session_id)
    oversight = can_oversee(request.user, session)
    subjects = subjects_visible_to(request.user, session).prefetch_related("assessments__sheet")
    sheets = sheets_visible_to(request.user).filter(
        assessment__exam_subject__cohort__session=session
    )
    candidates = candidates_visible_to(request.user).filter(session=session)
    query = request.GET.get("q", "")[:100]
    if query:
        candidates = candidates.filter(
            Q(student__first_name__icontains=query)
            | Q(student__last_name__icontains=query)
            | Q(student__admission_number__icontains=query)
        )
    return exam_render(
        request,
        "session",
        {
            "session": session,
            "oversight": oversight,
            "subjects": subjects,
            "sheets": sheets,
            "query": query,
            "page_obj": Paginator(candidates.order_by("student__first_name", "pk"), 25).get_page(
                request.GET.get("page")
            ),
            "events": session.events.select_related("actor")[:30] if oversight else [],
            "cohorts": session.cohorts.select_related("section__school_class") if oversight else [],
            "contributions": session.contributions.select_related("source") if oversight else [],
            "controllers": session.controllers.all() if oversight else [],
            "configuration_error": configuration_error(session) if oversight else "",
        },
    )


def configuration_error(session):
    from .services import validate_configuration

    try:
        validate_configuration(session)
    except ValidationError as exc:
        return "; ".join(exc.messages)
    return ""


@login_required
@require_http_methods(["GET", "POST"])
def transition(request, session_id, action):
    session = get_object_or_404(sessions_visible_to(request.user), pk=session_id)
    if not can_oversee(request.user, session):
        raise PermissionDenied
    form = ActionForm(request.POST or None, initial={"expected_version": session.version})
    if request.method == "POST" and form.is_valid():
        try:
            session_action(
                request.user,
                session.pk,
                action,
                expected_version=form.cleaned_data["expected_version"],
                reason=form.cleaned_data["reason"],
            )
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(request, "Examination state updated.")
            return redirect("examinations:session", session_id=session.pk)
    return exam_render(
        request,
        "form",
        {
            "form": form,
            "title": f"{action.title()} examination",
            "description": str(session),
            "confirmation": True,
        },
    )


@login_required
@require_GET
def schedules(request):
    ensure_access(request.user)
    field = forms.ModelChoiceField(queryset=sessions_visible_to(request.user), required=False)
    try:
        session = (
            field.clean(request.GET.get("session")) or sessions_visible_to(request.user).first()
        )
    except ValidationError as exc:
        raise Http404 from exc
    rows = ExamSchedule.objects.none()
    if session:
        rows = (
            ExamSchedule.objects.filter(assessment__exam_subject__cohort__session=session)
            .select_related("assessment__exam_subject__subject", "section__school_class", "room")
            .prefetch_related("invigilators")
        )
        if not can_oversee(request.user, session):
            personal_cohorts = session.candidates.filter(
                student__in=personal_students(request.user)
            ).values("cohort_id")
            rows = rows.filter(
                Q(assessment__exam_subject__in=subjects_visible_to(request.user, session))
                | Q(assessment__exam_subject__cohort__in=personal_cohorts)
            )
    return exam_render(
        request,
        "schedules",
        {
            "session": session,
            "sessions": sessions_visible_to(request.user),
            "rows": rows,
            "print_mode": request.GET.get("format") == "print",
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def schedule_edit(request, session_id):
    session = get_object_or_404(sessions_visible_to(request.user), pk=session_id)
    require(request.user, "manage_examinations", session)
    with timezone.override(school_zone()):
        form = ScheduleForm(request.POST or None, session=session)
        if request.method == "POST" and form.is_valid():
            data = form.cleaned_data.copy()
            data["assessment_id"] = data.pop("assessment").pk
            try:
                save_schedule(request.user, **data)
            except (ValidationError, IntegrityError) as exc:
                form_errors(form, exc)
            else:
                messages.success(request, "Date sheet saved; conflicts checked.")
                return redirect("examinations:session", session_id=session.pk)
    return exam_render(
        request,
        "form",
        {
            "form": form,
            "title": "Schedule an assessment",
            "description": (
                f"{session} · Times use {school_zone()}. "
                "Saving an existing assessment reschedules it before submission."
            ),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def marks_entry(request, sheet_id):
    sheet = get_object_or_404(sheets_visible_to(request.user), pk=sheet_id)
    session = sheet.assessment.exam_subject.cohort.session
    candidates = list(
        ExamCandidate.objects.filter(cohort=sheet.assessment.exam_subject.cohort)
        .select_related("student", "enrollment")
        .order_by("enrollment__roll_number", "student__first_name", "pk")
    )
    if len(candidates) > 1500:
        return exam_render(
            request,
            "form",
            {
                "title": "Roster exceeds supported entry size",
                "description": "Use sections with at most 1,500 candidates per marks sheet.",
            },
            status=400,
        )
    entries = {str(e.candidate_id): e for e in sheet.entries.all()}
    initial = [
        {
            "candidate": c.pk,
            "status": entries[str(c.pk)].status if str(c.pk) in entries else "pending",
            "marks": entries[str(c.pk)].marks if str(c.pk) in entries else None,
            "remarks": entries[str(c.pk)].remarks if str(c.pk) in entries else "",
        }
        for c in candidates
    ]
    formset = MarkRows(request.POST if request.method == "POST" else None, initial=initial)
    action_form = MarksActionForm(
        request.POST if request.method == "POST" else None,
        initial={"expected_version": sheet.version, "action": "draft"},
    )
    editable = (
        capable(request.user, "enter_marks")
        and session.state == "open"
        and sheet.state in ("draft", "returned")
    )
    if request.method == "POST":
        if not editable:
            raise PermissionDenied
        if formset.is_valid() and action_form.is_valid():
            rows = {
                str(row["candidate"]): {k: row[k] for k in ("status", "marks", "remarks")}
                for row in formset.cleaned_data
            }
            if len(rows) != len(formset.cleaned_data):
                action_form.add_error(
                    None, "A student was submitted more than once. Reload the roster."
                )
            else:
                try:
                    save_marks(
                        request.user,
                        sheet.pk,
                        rows,
                        expected_version=action_form.cleaned_data["expected_version"],
                        submit=action_form.cleaned_data["action"] == "submit",
                    )
                except (ValidationError, IntegrityError) as exc:
                    form_errors(action_form, exc)
                else:
                    messages.success(
                        request,
                        "Marks submitted for review."
                        if action_form.cleaned_data["action"] == "submit"
                        else "Draft marks saved.",
                    )
                    return redirect("examinations:marks", sheet_id=sheet.pk)
    display = []
    for index, row_form in enumerate(formset.forms):
        candidate = candidates[index] if index < len(candidates) else None
        display.append(
            {
                "form": row_form,
                "candidate": candidate,
                "entry": entries.get(str(candidate.pk)) if candidate else None,
            }
        )
    return exam_render(
        request,
        "marks",
        {
            "sheet": sheet,
            "session": session,
            "rows": display,
            "formset": formset,
            "action_form": action_form,
            "editable": editable,
            "oversight": can_oversee(request.user, session),
            "recorded": len(entries),
            "total": len(candidates),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def sheet_review(request, sheet_id):
    sheet = get_object_or_404(sheets_visible_to(request.user), pk=sheet_id)
    session = sheet.assessment.exam_subject.cohort.session
    require(request.user, "review_results", session)
    form = ReviewForm(request.POST or None, initial={"expected_version": sheet.version})
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            review_sheet(
                request.user,
                sheet.pk,
                data["decision"],
                expected_version=data["expected_version"],
                reason=data["reason"],
            )
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(request, "Marks review recorded.")
            return redirect("examinations:marks", sheet_id=sheet.pk)
    return exam_render(
        request,
        "form",
        {
            "form": form,
            "title": "Review marks submission",
            "description": str(sheet.assessment),
            "confirmation": True,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def candidate_detail(request, candidate_id):
    candidate = get_object_or_404(candidates_visible_to(request.user), pk=candidate_id)
    if not can_oversee(request.user, candidate.session):
        result = (
            current_results(request.user, session=candidate.session)
            .filter(candidate=candidate)
            .first()
        )
        if not result:
            raise Http404
        return redirect("examinations:report", result_id=result.pk)
    form = CandidateForm(
        request.POST or None,
        initial={
            "expected_version": candidate.session.version,
            **{
                k: getattr(candidate, k)
                for k in ("teacher_remarks", "principal_remarks", "withheld", "withholding_reason")
            },
        },
    )
    if request.method == "POST" and form.is_valid():
        try:
            update_candidate(request.user, candidate.pk, **form.cleaned_data)
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(request, "Candidate remarks saved.")
            return redirect("examinations:candidate", candidate_id=candidate.pk)
    calculation = (
        calculate_candidate(candidate) if candidate.session.report_kind == "assessment" else None
    )
    return exam_render(
        request,
        "candidate",
        {
            "candidate": candidate,
            "form": form,
            "calculation": calculation,
            "results": results_visible_to(request.user)
            .filter(candidate=candidate)
            .order_by("-publication__version"),
            "overrides": candidate.recommendation_overrides.select_related(
                "actor", "publication"
            ).order_by("-created_at"),
        },
    )


@login_required
@require_GET
def results(request):
    ensure_access(request.user)
    form = ResultFilters(request.GET, actor=request.user)
    rows = current_results(request.user)
    if form.is_valid():
        data = form.cleaned_data
        if data["session"]:
            rows = rows.filter(publication__session=data["session"])
        if data["query"]:
            rows = rows.filter(
                Q(candidate__student__first_name__icontains=data["query"])
                | Q(candidate__student__last_name__icontains=data["query"])
                | Q(candidate__student__admission_number__icontains=data["query"])
            )
        if data["outcome"]:
            rows = rows.filter(data__outcome=data["outcome"])
        sort = data["sort"]
        if sort in ("percentage", "-percentage"):
            from django.db.models import DecimalField, F
            from django.db.models.fields.json import KeyTextTransform
            from django.db.models.functions import Cast

            rows = rows.annotate(
                value=Cast(
                    KeyTextTransform("raw_percentage", "data"),
                    DecimalField(max_digits=20, decimal_places=10),
                )
            )
            rows = rows.order_by(
                F("value").desc(nulls_last=True)
                if sort.startswith("-")
                else F("value").asc(nulls_last=True),
                "pk",
            )
        else:
            rows = rows.order_by(
                "candidate__student__first_name", "candidate__student__last_name", "pk"
            )
    else:
        rows = rows.none()
    if request.GET.get("format") == "csv":
        if rows.count() > MAX_RESULTS:
            form.add_error(None, "Narrow the report to at most 5,000 results before exporting.")
        elif form.is_valid():
            stream = StringIO()
            writer = csv.writer(stream)
            writer.writerow(
                [
                    "Examination",
                    "Academic year",
                    "Admission",
                    "Student",
                    "Class",
                    "Section",
                    "Percentage",
                    "Grade",
                    "Outcome",
                    "Version",
                ]
            )
            for row in rows:
                d = row.data
                writer.writerow(
                    [
                        safe_csv(d.get(k))
                        for k in (
                            "session",
                            "year",
                            "admission",
                            "student",
                            "class",
                            "section",
                            "percentage",
                            "grade",
                            "outcome",
                            "version",
                        )
                    ]
                )
            response = HttpResponse(
                stream.getvalue().encode("utf-8-sig"), content_type="text/csv; charset=utf-8"
            )
            response["Content-Disposition"] = 'attachment; filename="published-results.csv"'
            response["Cache-Control"] = "private, no-store"
            record_event("exam.results_csv", actor=request.user)
            return response
    return exam_render(
        request,
        "results",
        {"form": form, "page_obj": Paginator(rows, 25).get_page(request.GET.get("page"))},
    )


def permitted_report(user, result_id):
    result = get_object_or_404(results_visible_to(user), pk=result_id)
    if not can_oversee(user, result.publication.session):
        current = result.candidate.results.order_by("-publication__version").first()
        if current and current.data["outcome"] == "withheld" and current.pk != result.pk:
            raise Http404
    return result


@login_required
@require_GET
def report(request, result_id):
    result = permitted_report(request.user, result_id)
    if request.GET.get("format") == "pdf":
        return report_pdf(request.user, result)
    latest = result.publication.session.publications.first()
    record_event("exam.report_viewed", actor=request.user, target=result.pk)
    history = (
        results_visible_to(request.user)
        .filter(candidate=result.candidate)
        .order_by("-publication__version")
    )
    if result.data["outcome"] == "withheld" and not can_oversee(
        request.user, result.publication.session
    ):
        history = history.filter(pk=result.pk)
    return exam_render(
        request,
        "report",
        {
            "result": result,
            "data": result.data,
            "is_current": result.publication_id == latest.pk,
            "history": history,
            "print_mode": request.GET.get("format") == "print",
        },
    )


@login_required
@require_GET
def report_image(request, result_id, kind):
    result = permitted_report(request.user, result_id)
    value = (
        result.data["school"].get("logo")
        if kind == "logo"
        else result.data.get("photo")
        if kind == "photo"
        else None
    )
    if not value:
        raise Http404
    response = HttpResponse(base64.b64decode(value), content_type="image/png")
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_GET
def analysis(request, session_id):
    session = get_object_or_404(sessions_visible_to(request.user), pk=session_id)
    if (
        not can_oversee(request.user, session)
        and not subjects_visible_to(request.user, session).exists()
    ):
        raise PermissionDenied
    try:
        data = analytics(request.user, session)
    except ValidationError as exc:
        return exam_render(
            request,
            "form",
            {"title": "Analytics unavailable", "description": "; ".join(exc.messages)},
            status=400,
        )
    chart = {"grades": data["grades"], "subjects": data["subjects"], "sections": data["sections"]}
    return exam_render(
        request, "analytics", {"session": session, "analytics": data, "chart": chart}
    )


@login_required
@require_GET
def corrections(request):
    ensure_access(request.user)
    rows = corrections_visible_to(request.user).order_by("-created_at")
    state = request.GET.get("state", "pending")
    if state in ("pending", "approved", "rejected"):
        rows = rows.filter(state=state)
    return exam_render(
        request,
        "corrections",
        {
            "page_obj": Paginator(rows, 25).get_page(request.GET.get("page")),
            "state": state,
            "amendments": amendments_visible_to(request.user).order_by("-created_at")[:50],
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def correction_request(request, entry_id):
    entry = get_object_or_404(
        MarkEntry.objects.filter(sheet__in=sheets_visible_to(request.user)).select_related(
            "candidate__student", "sheet__assessment__exam_subject__cohort__session"
        ),
        pk=entry_id,
    )
    require(request.user, "correct_results")
    form = CorrectionForm(
        request.POST or None,
        initial={"status": entry.status, "marks": entry.marks, "remarks": entry.remarks},
    )
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data.copy()
        data.pop("confirm")
        try:
            request_correction(request.user, entry.pk, **data)
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(
                request, "Correction requested. Existing results remain unchanged until approval."
            )
            return redirect("examinations:corrections")
    return exam_render(
        request,
        "form",
        {
            "form": form,
            "title": "Request a result correction",
            "description": (
                f"{entry.candidate.student} · {entry.sheet.assessment} · "
                f"Original: {entry.status}, {entry.marks}"
            ),
            "confirmation": True,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def correction_decision(request, correction_id):
    correction = get_object_or_404(corrections_visible_to(request.user), pk=correction_id)
    session = correction.entry.sheet.assessment.exam_subject.cohort.session
    require(request.user, "decide_corrections", session)
    form = CorrectionDecisionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            decide_correction(
                request.user,
                correction.pk,
                approve=form.cleaned_data["approve"] == "yes",
                reason=form.cleaned_data["reason"],
            )
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(request, "Independent correction decision recorded.")
            return redirect("examinations:corrections")
    return exam_render(
        request,
        "form",
        {
            "form": form,
            "title": "Review result correction",
            "description": correction.reason,
            "correction": correction,
            "confirmation": True,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def recommendation(request, candidate_id):
    candidate = get_object_or_404(candidates_visible_to(request.user), pk=candidate_id)
    require(request.user, "override_promotion", candidate.session)
    form = RecommendationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            override_recommendation(
                request.user,
                candidate.pk,
                eligible=form.cleaned_data["eligible"] == "yes",
                reason=form.cleaned_data["reason"],
            )
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(
                request, "Promotion recommendation recorded. Enrollment history is unchanged."
            )
            return redirect("examinations:candidate", candidate_id=candidate.pk)
    return exam_render(
        request,
        "form",
        {
            "form": form,
            "title": "Record promotion recommendation override",
            "description": str(candidate),
            "confirmation": True,
        },
    )


@login_required
@require_GET
def notifications(request):
    ensure_access(request.user)
    return exam_render(
        request,
        "notifications",
        {
            "page_obj": Paginator(
                notifications_visible_to(request.user).order_by("-created_at"), 25
            ).get_page(request.GET.get("page"))
        },
    )


@login_required
@require_POST
def notification_read(request, pk):
    notification = get_object_or_404(notifications_visible_to(request.user), pk=pk)
    if not notification.read_at:
        notification.read_at = timezone.now()
        notification.save(update_fields=["read_at", "updated_at"])
    return redirect("examinations:notifications")


@login_required
@require_http_methods(["GET", "POST"])
def amendment_request(request, candidate_id):
    candidate = get_object_or_404(candidates_visible_to(request.user), pk=candidate_id)
    require(request.user, "correct_results", candidate.session)
    form = AmendmentForm(
        request.POST or None,
        initial={
            "expected_version": candidate.session.version,
            **{
                k: getattr(candidate, k)
                for k in ("teacher_remarks", "principal_remarks", "withheld", "withholding_reason")
            },
        },
    )
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data.copy()
        data.pop("confirm")
        try:
            request_amendment(request.user, candidate.pk, **data)
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(request, "Result amendment requested for independent review.")
            return redirect("examinations:corrections")
    return exam_render(
        request,
        "form",
        {
            "form": form,
            "title": "Request remarks or visibility amendment",
            "description": str(candidate),
            "confirmation": True,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def amendment_decision(request, amendment_id):
    amendment = get_object_or_404(amendments_visible_to(request.user), pk=amendment_id)
    require(request.user, "decide_corrections", amendment.candidate.session)
    form = CorrectionDecisionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            decide_amendment(
                request.user,
                amendment.pk,
                approve=form.cleaned_data["approve"] == "yes",
                reason=form.cleaned_data["reason"],
            )
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(request, "Result amendment decision recorded.")
            return redirect("examinations:corrections")
    return exam_render(
        request,
        "form",
        {
            "form": form,
            "title": "Review candidate amendment",
            "description": amendment.reason,
            "amendment": amendment,
            "confirmation": True,
        },
    )
