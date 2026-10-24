from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from core.branding import school_branding
from core.models import SchoolSettings
from finance.exports import pdf_document
from people.models import GuardianStudent

from .forms import RequestForm
from .models import DocumentRequest, IssuedDocument
from .services import create_request


def visible(user):
    rows = DocumentRequest.objects.select_related("document_type", "student", "employee")
    if user.has_perm("certificates.view_all_certificates"):
        return rows
    linked = GuardianStudent.objects.filter(guardian__user=user).values("student_id")
    from django.db.models import Q

    return rows.filter(Q(student__user=user) | Q(student_id__in=linked) | Q(employee__user=user))


@login_required
def overview(request):
    rows = visible(request.user)
    personal = any(
        request.user.has_perm(permission)
        for permission in (
            "accounts.access_student_dashboard",
            "accounts.access_parent_dashboard",
            "accounts.access_teacher_dashboard",
        )
    )
    if (
        not rows.exists()
        and not request.user.has_perm("certificates.manage_certificates")
        and not personal
    ):
        raise PermissionDenied
    return render(
        request,
        "operations/phase8_dashboard.html",
        {
            "title": "Certificates and official documents",
            "description": (
                "Controlled requests, independent approval, immutable issuance and "
                "privacy-preserving verification."
            ),
            "metrics": [
                ("Visible requests", rows.count()),
                ("Issued", rows.filter(state="issued").count()),
            ],
            "sections": [
                {
                    "title": "Requests",
                    "help": "Issued documents remain immutable; revocation creates history.",
                    "headings": ["Type", "Subject", "State", "Requested"],
                    "rows": [
                        (
                            x.document_type.name,
                            str(x.student) if x.student_id else x.employee.name,
                            x.get_state_display(),
                            x.created_at,
                        )
                        for x in rows[:50]
                    ],
                }
            ],
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def request_document(request):
    form = RequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            create_request(request.user, form.save(commit=False))
        except (PermissionDenied, ValidationError) as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Document request submitted.")
            return redirect("certificates:overview")
    return render(
        request,
        "operations/phase7_form.html",
        {
            "title": "Request official document",
            "hint": (
                "A request requires eligibility review and does not issue a document automatically."
            ),
            "form": form,
        },
    )


@login_required
def download(request, pk):
    issued = get_object_or_404(
        IssuedDocument.objects.select_related("request", "signatory"),
        request__in=visible(request.user),
        pk=pk,
        state="valid",
    )
    snap = issued.snapshot
    return pdf_document(
        snap["type"],
        school_branding(),
        ["Official statement"],
        [(snap["wording"],)],
        identity=(
            ("Certificate number", issued.number),
            ("Issued to", snap["school_subject"]),
            ("Issue date", issued.issued_at.date()),
            ("Signatory", f"{issued.signatory.name}, {issued.signatory.title}"),
            ("Verification reference", issued.verification_token),
        ),
        status="Valid",
        filename=f"certificate-{issued.number}.pdf",
    )


def verify(request, token):
    issued = get_object_or_404(
        IssuedDocument.objects.select_related("request__document_type"), verification_token=token
    )
    return render(
        request,
        "certificates/verify.html",
        {"document": issued, "school": SchoolSettings.objects.first()},
    )
