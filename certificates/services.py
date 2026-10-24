from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from audit.services import record_event
from people.models import GuardianStudent

from .models import DocumentHistory, DocumentRequest, IssuedDocument


def can_request(actor, row):
    if row.student_id:
        return (
            row.student.user_id == actor.pk
            or GuardianStudent.objects.filter(student=row.student, guardian__user=actor).exists()
        )
    return row.employee.user_id == actor.pk


@transaction.atomic
def create_request(actor, row):
    if not actor.is_active or (
        not can_request(actor, row) and not actor.has_perm("certificates.manage_certificates")
    ):
        raise PermissionDenied
    if row.student_id and row.document_type.audience not in ("student", "both"):
        raise ValidationError("This document type is not available to students.")
    if row.employee_id and row.document_type.audience not in ("staff", "both"):
        raise ValidationError("This document type is not available to staff.")
    row.requested_by = actor
    row.full_clean()
    row.save()
    DocumentHistory.objects.create(request=row, actor=actor, action="requested")
    record_event("certificates.requested", actor=actor, target=row.pk)
    return row


@transaction.atomic
def decide(actor, request_id, approve, reason=""):
    if not actor.is_active or not actor.has_perm("certificates.approve_certificates"):
        raise PermissionDenied
    row = DocumentRequest.objects.select_for_update().get(pk=request_id)
    if row.state not in ("requested", "draft") or actor.pk == row.requested_by_id:
        raise ValidationError("An independent reviewer must decide a pending request.")
    row.state = "approved" if approve else "rejected"
    row.reviewed_by, row.reason = actor, reason
    row.save()
    DocumentHistory.objects.create(request=row, actor=actor, action=row.state, reason=reason)
    return row


@transaction.atomic
def issue(actor, request_id, signatory):
    if not actor.is_active or not actor.has_perm("certificates.approve_certificates"):
        raise PermissionDenied
    row = (
        DocumentRequest.objects.select_for_update(of=("self",))
        .select_related("document_type", "student", "employee")
        .get(pk=request_id)
    )
    if row.state != "approved" or hasattr(row, "issued"):
        raise ValidationError("Only an approved, unissued request can be issued.")
    subject = row.student or row.employee
    name = str(subject) if row.student else row.employee.name
    issued = IssuedDocument.objects.create(
        request=row,
        number=f"CERT-{timezone.localdate():%Y}-{str(row.pk)[:8].upper()}",
        issued_at=timezone.now(),
        issued_by=actor,
        signatory=signatory,
        snapshot={
            "type": row.document_type.name,
            "school_subject": name,
            "wording": row.document_type.template_text,
            "signatory": {"name": signatory.name, "title": signatory.title},
        },
    )
    row.state = "issued"
    row.save(update_fields=["state", "updated_at"])
    DocumentHistory.objects.create(request=row, actor=actor, action="issued")
    record_event("certificates.issued", actor=actor, target=issued.pk)
    from communications.notices import add

    recipients = [row.student.user_id] if row.student_id else [row.employee.user_id]
    if row.student_id:
        recipients += list(
            GuardianStudent.objects.filter(student=row.student).values_list(
                "guardian__user_id", flat=True
            )
        )
    for recipient in recipients:
        add(
            recipient,
            f"certificate:{issued.pk}:issued",
            f"Issued: {row.document_type.name}",
            f"/certificates/documents/{issued.pk}/",
            category_name="certificates",
            student=row.student if row.student_id else None,
        )
    return issued


@transaction.atomic
def revoke(actor, document_id, reason):
    if not actor.has_perm("certificates.approve_certificates") or not reason.strip():
        raise PermissionDenied
    row = IssuedDocument.objects.select_for_update().get(pk=document_id)
    if row.state != "valid":
        raise ValidationError("Only valid documents can be revoked.")
    row.state, row.revoked_at, row.revocation_reason = "revoked", timezone.now(), reason
    row.save()
    row.request.state = "revoked"
    row.request.save(update_fields=["state", "updated_at"])
    DocumentHistory.objects.create(
        request=row.request, actor=actor, action="revoked", reason=reason
    )
    return row
