from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from .forms import IssueForm
from .models import Book, Copy, Loan, Membership
from .services import issue, return_copy


def membership(user):
    return Membership.objects.filter(
        Q(student__user=user) | Q(employee__user=user), is_active=True
    ).first()


@login_required
def overview(request):
    member = membership(request.user)
    manage = request.user.has_perm("library.manage_library")
    if (
        not member
        and not manage
        and not (
            request.user.has_perm("accounts.access_student_dashboard")
            or request.user.has_perm("accounts.access_teacher_dashboard")
        )
    ):
        raise PermissionDenied
    loans = (
        Loan.objects.select_related("copy__book", "membership")
        if manage
        else member.loans.all().select_related("copy__book")
        if member
        else Loan.objects.none()
    )
    return render(
        request,
        "operations/phase8_dashboard.html",
        {
            "title": "School library",
            "description": (
                "Searchable title/copy catalog with controlled circulation and personal "
                "borrowing history."
            ),
            "metrics": [
                ("Titles", Book.objects.count()),
                ("Available copies", Copy.objects.filter(status="available").count()),
                ("Issued", Copy.objects.filter(status="issued").count()),
            ],
            "sections": [
                {
                    "title": "Loans",
                    "help": "Personal borrowers see only their own history.",
                    "headings": ["Title", "Accession", "Due", "State"],
                    "rows": [
                        (
                            x.copy.book.title,
                            x.copy.accession_number,
                            x.due_at,
                            x.get_state_display(),
                        )
                        for x in loans[:50]
                    ],
                }
            ],
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def issue_view(request):
    if not request.user.has_perm("library.manage_library"):
        raise PermissionDenied
    form = IssueForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        issue(request.user, form.cleaned_data["copy"].pk, form.cleaned_data["membership"].pk)
        messages.success(request, "Book issued.")
        return redirect("library:overview")
    return render(
        request,
        "operations/phase7_form.html",
        {
            "title": "Issue a library copy",
            "hint": "Availability and borrowing limits are rechecked transactionally.",
            "form": form,
        },
    )


@login_required
@require_POST
def return_view(request, pk):
    return_copy(request.user, pk, condition=request.POST.get("condition", "good"))
    messages.success(request, "Book returned.")
    return redirect("library:overview")
