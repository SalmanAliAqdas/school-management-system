import csv
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from scheduling.access import children, current_assignments, selected_child

from . import forms, selectors, services
from .models import Assignment, Attachment, Submission


def status(assignment, submission):
    if submission:
        version = submission.versions.first()
        return (
            "Submitted late"
            if submission.state == "submitted" and version and version.late
            else submission.get_state_display()
        )
    if assignment.submission_required and timezone.now() > assignment.due_at:
        return "Overdue"
    return "Not submitted" if assignment.submission_required else "Reading / no submission"


@login_required
def overview(request):
    rows = selectors.visible(request.user).order_by("-publish_at")
    child = selected_child(request)
    if child:
        from django.db.models import Exists, OuterRef, Q

        from people.models import Enrollment

        placed = Enrollment.objects.filter(
            student=child,
            academic_year_id=OuterRef("teaching__academic_year_id"),
            section_id=OuterRef("teaching__section_id"),
            started_on__lte=OuterRef("publish_at__date"),
        ).filter(Q(ended_on__isnull=True) | Q(ended_on__gte=OuterRef("publish_at__date")))
        rows = rows.alias(child_eligible=Exists(placed)).filter(
            child_eligible=True,
            state__in=["scheduled", "closed", "archived"],
            publish_at__lte=timezone.now(),
        )
    if request.GET.get("q"):
        rows = rows.filter(title__icontains=request.GET["q"][:100])
    bucket = request.GET.get("status", "")
    now = timezone.now()
    if bucket == "today":
        rows = rows.filter(publish_at__date=timezone.localdate())
    elif bucket == "upcoming":
        rows = rows.filter(due_at__gte=now, state="scheduled")
    elif bucket == "due_soon":
        rows = rows.filter(due_at__range=(now, now + timedelta(days=2)), state="scheduled")
    elif bucket == "overdue":
        rows = rows.filter(due_at__lt=now, submission_required=True).exclude(state="draft")
    elif bucket in ("submitted", "reviewed", "graded", "returned"):
        match = Submission.objects.filter(state=bucket)
        if (
            not request.user.has_perm("learning.manage_learning")
            and not current_assignments(request.user).exists()
        ):
            match = match.filter(student__in=children(request.user))
        if child:
            match = match.filter(student=child)
        rows = rows.filter(pk__in=match.values("assignment_id"))
    page = Paginator(rows, 20).get_page(request.GET.get("page"))
    cards = []
    for assignment in page:
        submission_rows = selectors.submissions(request.user, assignment)
        if child:
            submission_rows = submission_rows.filter(student=child)
        submission_rows = list(submission_rows)
        cards.append(
            {
                "assignment": assignment,
                "status": status(assignment, submission_rows[0] if submission_rows else None),
                "count": len(submission_rows),
            }
        )
    return render(
        request,
        "learning/overview.html",
        {
            "page": page,
            "cards": cards,
            "children": children(request.user),
            "selected_child": child,
            "can_create": request.user.has_perm("learning.manage_learning")
            or current_assignments(request.user).exists(),
            "active_nav": "homework",
        },
    )


@login_required
def edit(request, pk=None):
    row = get_object_or_404(selectors.visible(request.user), pk=pk) if pk else Assignment()
    if pk:
        services.authorize(request.user, row)
    form = forms.AssignmentForm(
        request.POST or None,
        request.FILES or None,
        instance=row,
        initial={"expected": row.revision if pk else None},
    )
    if not request.user.has_perm("learning.manage_learning"):
        form.fields["teaching"].queryset = current_assignments(request.user)
    if not form.fields["teaching"].queryset.exists():
        raise PermissionDenied
    if request.method == "POST" and form.is_valid():
        try:
            row = services.save_assignment(
                request.user,
                form.save(commit=False),
                form.cleaned_data["expected"],
                form.cleaned_data["files"],
            )
            return redirect("learning:detail", pk=row.pk)
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(
        request,
        "operations/phase7_form.html",
        {
            "form": form,
            "title": "Learning assignment",
            "hint": (
                "Dates use the school timezone. Published changes retain "
                "history and notify recipients."
            ),
        },
    )


@login_required
def detail(request, pk):
    row = get_object_or_404(selectors.visible(request.user), pk=pk)
    reviewer = selectors.can_review(request.user, row)
    subs = selectors.submissions(request.user, row).order_by("student__first_name")
    progress = []
    for sub in subs:
        feedback = sub.feedback.all()
        if not reviewer:
            feedback = feedback.filter(released=True)
            if sub.student.user_id != request.user.pk:
                feedback = feedback.filter(guardian_visible=True)
        progress.append(
            {
                "row": sub,
                "versions": sub.versions.prefetch_related("attachments"),
                "feedback": feedback,
                "status": status(row, sub),
            }
        )
    missing = []
    if reviewer and timezone.now() > row.due_at and row.submission_required:
        missing = selectors.roster(row).exclude(
            student_id__in=subs.exclude(state="draft").values("student_id")
        )
    own = subs.filter(student__user=request.user).first()
    return render(
        request,
        "learning/detail.html",
        {
            "assignment": row,
            "reviewer": reviewer,
            "progress": progress,
            "missing": missing,
            "can_submit": request.user.has_perm("accounts.access_student_dashboard")
            and selectors.roster(row).filter(student__user=request.user).exists(),
            "own": own,
            "supporting": row.attachments.filter(version__isnull=True),
            "active_nav": "homework",
        },
    )


@login_required
@require_POST
def action(request, pk, action):
    get_object_or_404(selectors.visible(request.user), pk=pk)
    try:
        services.transition(request.user, pk, action)
        messages.success(request, "Assignment updated.")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect("learning:detail", pk=pk)


@login_required
def submit(request, pk):
    row = get_object_or_404(selectors.visible(request.user), pk=pk)
    if (
        not request.user.has_perm("accounts.access_student_dashboard")
        or not selectors.roster(row).filter(student__user=request.user).exists()
    ):
        raise PermissionDenied
    sub = Submission.objects.filter(assignment=row, student__user=request.user).first()
    previous = sub.versions.first() if sub else None
    form = forms.SubmissionForm(
        request.POST or None,
        request.FILES or None,
        initial={"expected": sub.revision if sub else 0, "text": previous.text if previous else ""},
    )
    if request.method == "POST" and form.is_valid():
        try:
            services.submit(request.user, pk, **form.cleaned_data)
            return redirect("learning:detail", pk=pk)
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(
        request,
        "operations/phase7_form.html",
        {
            "form": form,
            "title": "Submit: " + row.title,
            "hint": (
                "Each save creates a preserved version. Reattach files for the "
                "new version; earlier files remain in history. PDF, text, PNG and JPEG; "
                "up to five files, 5 MB each."
            ),
        },
    )


@login_required
def review(request, pk):
    sub = get_object_or_404(Submission, pk=pk)
    services.authorize(request.user, sub.assignment)
    form = forms.FeedbackForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.review(request.user, pk, **form.cleaned_data)
            return redirect("learning:detail", pk=sub.assignment_id)
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(
        request,
        "operations/phase7_form.html",
        {
            "form": form,
            "title": f"Review work · {sub.student}",
            "hint": (
                "Feedback stays private until release is checked. Each "
                "correction retains the preceding review."
            ),
        },
    )


def file_response(row):
    response = HttpResponse(bytes(row.data), content_type="application/octet-stream")
    response["Content-Disposition"] = f'attachment; filename="{row.filename}"'
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
def attachment(request, pk):
    row = get_object_or_404(
        Attachment.objects.defer("data"), pk=pk, assignment__in=selectors.visible(request.user)
    )
    if (
        row.version_id
        and not selectors.submissions(request.user, row.assignment)
        .filter(pk=row.version.submission_id)
        .exists()
    ):
        raise PermissionDenied
    return file_response(row)


@login_required
def export(request, pk):
    row = get_object_or_404(selectors.visible(request.user), pk=pk)
    services.authorize(request.user, row)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="assignment-summary.csv"'
    writer = csv.writer(response)
    writer.writerow(["Student number", "Status", "Marks", "Released"])
    for sub in selectors.submissions(request.user, row):
        feedback = sub.feedback.first()
        number = sub.student.admission_number
        writer.writerow(
            [
                "'" + number if number[:1] in "=+-@" else number,
                status(row, sub),
                feedback.marks if feedback else "",
                feedback.released if feedback else False,
            ]
        )
    return response


@login_required
def reports(request):
    from .reporting import reports as report_rows

    if (
        not request.user.has_perm("learning.manage_learning")
        and not current_assignments(request.user).exists()
    ):
        raise PermissionDenied
    return render(request, "learning/reports.html", {"reports": report_rows(request.user)})


@login_required
def excuse(request, pk, student_id):
    from django import forms as django_forms

    assignment = get_object_or_404(selectors.visible(request.user), pk=pk)
    services.authorize(request.user, assignment)

    class ExcuseForm(django_forms.Form):
        reason = django_forms.CharField(max_length=1000, widget=django_forms.Textarea)

    form = ExcuseForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.excuse(request.user, pk, student_id, form.cleaned_data["reason"])
            return redirect("learning:detail", pk=pk)
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(
        request, "operations/phase7_form.html", {"form": form, "title": "Excuse assignment"}
    )
