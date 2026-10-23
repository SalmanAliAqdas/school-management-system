from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from attendance.calendar import school_now
from learning.views import file_response
from scheduling.access import children, current_assignments, require

from . import forms, selectors, services
from .models import CommunicationPolicy, Document, Message, Publication, PublicationRead, Report


@login_required
def overview(request):
    rows = selectors.publications(request.user, management=True).order_by("-pinned", "-publish_at")
    if request.GET.get("kind") in ("event", "announcement"):
        rows = rows.filter(kind=request.GET["kind"])
    if request.GET.get("q"):
        rows = rows.filter(title__icontains=request.GET["q"][:100])
    return render(
        request,
        "communications/overview.html",
        {
            "page": Paginator(rows, 20).get_page(request.GET.get("page")),
            "active_nav": "communications",
        },
    )


@login_required
def edit(request, pk=None):
    require(request.user, "communications.manage_communications")
    row = get_object_or_404(Publication, pk=pk) if pk else Publication(author=request.user)
    form = forms.PublicationForm(
        request.POST or None,
        request.FILES or None,
        instance=row,
        initial={"expected": row.revision if pk else None},
    )
    if request.method == "POST" and form.is_valid():
        try:
            row = services.save_publication(
                request.user,
                form.save(commit=False),
                form.cleaned_data["expected"],
                form.cleaned_data["files"],
            )
            return redirect("communications:publication", pk=row.pk)
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(
        request,
        "operations/phase7_form.html",
        {
            "form": form,
            "title": "Event or announcement",
            "hint": (
                "Informational events never change attendance eligibility. "
                "School closures remain in the attendance calendar workflow."
            ),
        },
    )


@login_required
def publication(request, pk):
    row = get_object_or_404(selectors.publications(request.user, management=True), pk=pk)
    return render(
        request,
        "communications/publication.html",
        {"publication": row, "active_nav": "communications"},
    )


@login_required
@require_POST
def publication_action(request, pk, action):
    if action == "read":
        row = get_object_or_404(selectors.publications(request.user), pk=pk)
        PublicationRead.objects.get_or_create(publication=row, user=request.user)
    else:
        try:
            services.publication_action(request.user, pk, action, request.POST.get("reason", ""))
            messages.success(request, "Publication updated.")
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
    return redirect("communications:publication", pk=pk)


@login_required
def inbox(request):
    rows = selectors.conversations(request.user).order_by("-updated_at")
    if request.GET.get("q"):
        rows = rows.filter(subject__icontains=request.GET["q"][:100])
    page = Paginator(rows, 20).get_page(request.GET.get("page"))
    for row in page:
        row.unread = row.messages.exclude(sender=request.user).filter(read_at__isnull=True).count()
    return render(request, "communications/inbox.html", {"page": page, "active_nav": "messages"})


@login_required
def compose(request):
    from people.models import Student

    child_rows = children(request.user)
    assigned = current_assignments(request.user)
    if assigned.exists():
        child_rows = Student.objects.filter(
            Q(pk__in=child_rows)
            | Q(
                enrollments__section_id__in=assigned.values("section_id"),
                enrollments__academic_year_id__in=assigned.values("academic_year_id"),
                enrollments__is_active=True,
            )
        ).distinct()
    if request.user.has_perm("communications.manage_communications"):
        child_rows = Student.objects.all()
    form = forms.ConversationForm(request.POST or None, request.FILES or None)
    form.fields["student"].queryset = child_rows
    child_id = (
        request.POST.get("student") if request.method == "POST" else request.GET.get("student")
    )
    try:
        child = child_rows.filter(pk=child_id).first() if child_id else None
    except (ValidationError, ValueError):
        child = None
    eligible = selectors.recipients(request.user, child)
    form.fields["recipient"].queryset = form.fields["recipient"].queryset.model.objects.filter(
        pk__in=[u.pk for u in eligible]
    )
    form.initial["student"] = child
    if request.method == "POST" and form.is_valid():
        try:
            row = services.send(request.user, **form.cleaned_data)
            return redirect("communications:thread", pk=row.pk)
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(
        request,
        "communications/compose.html",
        {
            "form": form,
            "children": child_rows,
            "selected_child": child,
            "title": "New conversation",
        },
    )


@login_required
def thread(request, pk):
    row = get_object_or_404(selectors.conversations(request.user), pk=pk)
    form = forms.MessageForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.send(request.user, conversation=pk, **form.cleaned_data)
            return redirect("communications:thread", pk=pk)
        except ValidationError as exc:
            form.add_error(None, exc)
    page = Paginator(
        row.messages.select_related("sender")
        .prefetch_related("documents")
        .order_by("-created_at", "-pk"),
        30,
    ).get_page(request.GET.get("page"))
    return render(
        request,
        "communications/thread.html",
        {"conversation": row, "page": page, "form": form, "active_nav": "messages"},
    )


@login_required
@require_POST
def read_thread(request, pk):
    row = get_object_or_404(selectors.conversations(request.user), pk=pk)
    row.messages.exclude(sender=request.user).filter(read_at__isnull=True).update(
        read_at=timezone.now()
    )
    from .models import Notice

    Notice.objects.filter(conversation=row, recipient=request.user, read_at__isnull=True).update(
        read_at=timezone.now()
    )
    return redirect("communications:thread", pk=pk)


@login_required
def document(request, pk):
    row = get_object_or_404(Document.objects.defer("data"), pk=pk)
    if row.publication_id:
        get_object_or_404(
            selectors.publications(request.user, management=True), pk=row.publication_id
        )
    elif row.message_id:
        get_object_or_404(selectors.conversations(request.user), pk=row.message.conversation_id)
        if row.message.hidden:
            raise PermissionDenied
    return file_response(row)


@login_required
def report(request, pk):
    message = get_object_or_404(
        Message, pk=pk, conversation__in=selectors.conversations(request.user)
    )
    form = forms.ReportForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.report_message(request.user, pk, **form.cleaned_data)
            messages.success(request, "Report sent to authorized moderators.")
            return redirect("communications:thread", pk=message.conversation_id)
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(
        request, "operations/phase7_form.html", {"form": form, "title": "Report a message"}
    )


@login_required
def moderation(request, pk=None):
    require(request.user, "communications.moderate_messages")
    if pk is None:
        return render(
            request,
            "communications/moderation.html",
            {"reports": Report.objects.select_related("reporter", "message").order_by("-pk")[:100]},
        )
    row = get_object_or_404(Report, pk=pk)
    form = forms.ModerationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.moderate(request.user, pk, **form.cleaned_data)
            return redirect("communications:moderation")
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(
        request,
        "operations/phase7_form.html",
        {"form": form, "title": "Moderation decision", "hint": row.reason},
    )


@login_required
def policy(request):
    require(request.user, "communications.publish_communications")
    row = CommunicationPolicy.objects.first() or CommunicationPolicy()
    form = forms.PolicyForm(request.POST or None, instance=row)
    if request.method == "POST" and form.is_valid():
        form.save()
        from audit.services import record_event

        record_event("communications.policy", actor=request.user, target=1)
        return redirect("communications:overview")
    return render(
        request,
        "operations/phase7_form.html",
        {
            "form": form,
            "title": "Communication policy",
            "hint": (
                "Retention is a minimum retention rule. No automatic deletion "
                "or message purge is performed."
            ),
        },
    )


@login_required
def calendar(request):
    from academics.models import AcademicYear
    from learning.selectors import visible as assignments
    from portals.services import calendar_items
    from scheduling.selectors import daily

    today = school_now().date()
    items = []
    selected = None
    child_rows = children(request.user)
    if request.GET.get("child"):
        selected = get_object_or_404(child_rows, pk=request.GET["child"])
    else:
        selected = child_rows.first()
    year = AcademicYear.objects.filter(is_current=True).first()
    if selected:
        role = "student" if selected.user_id == request.user.pk else "parent"
        items.extend(calendar_items(request.user, year, student=selected, role=role))
    elif request.user.has_perm("accounts.access_teacher_dashboard"):
        items.extend(calendar_items(request.user, year, teacher=True))
    for row in selectors.publications(request.user).filter(kind="event"):
        items.append(
            {
                "date": row.starts_at.astimezone(school_now().tzinfo).date(),
                "title": row.title + (" (cancelled)" if row.state == "cancelled" else ""),
                "category": row.category,
                "url": f"/communications/publications/{row.pk}/",
            }
        )
    for row in assignments(request.user).exclude(state="draft"):
        if (
            selected
            and not row.teaching.section.enrollments.filter(
                student=selected, academic_year=row.teaching.academic_year
            ).exists()
        ):
            continue
        items.append(
            {
                "date": row.due_at.astimezone(school_now().tzinfo).date(),
                "title": row.title,
                "category": "Homework due",
                "url": f"/learning/{row.pk}/",
            }
        )
    for offset in range(7):
        day = today + timedelta(days=offset)
        for row in daily(request.user, day, selected):
            items.append(
                {
                    "date": day,
                    "title": f"{row.period.starts_at:%H:%M} {row.assignment.subject} · {row.room}",
                    "category": "Lesson",
                    "url": f"/scheduling/{row.timetable_id}/",
                }
            )
    items = sorted(items, key=lambda i: (i["date"], i["title"]))
    return render(
        request,
        "communications/calendar.html",
        {
            "items": items,
            "children": child_rows,
            "selected_child": selected,
            "today": today,
            "active_nav": "calendar",
        },
    )
