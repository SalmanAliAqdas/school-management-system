import secrets
import uuid

from django.conf import settings
from django.db import models

from core.models import TimestampedModel


def verification_token():
    return secrets.token_urlsafe(32)


class DocumentType(TimestampedModel):
    name = models.CharField(max_length=140, unique=True)
    audience = models.CharField(
        max_length=12, choices=[("student", "Student"), ("staff", "Staff"), ("both", "Both")]
    )
    template_text = models.TextField(max_length=6000)
    requires_approval = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)


class Signatory(TimestampedModel):
    name = models.CharField(max_length=140)
    title = models.CharField(max_length=140)
    is_active = models.BooleanField(default=True)


class DocumentRequest(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document_type = models.ForeignKey(DocumentType, on_delete=models.PROTECT)
    student = models.ForeignKey(
        "people.Student",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="document_requests",
    )
    employee = models.ForeignKey(
        "hr.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="document_requests",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="requested_documents"
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reviewed_documents",
    )
    purpose = models.CharField(max_length=500)
    state = models.CharField(
        max_length=16,
        default="requested",
        choices=[
            (x, x.title())
            for x in ["requested", "draft", "approved", "rejected", "issued", "revoked"]
        ],
    )
    reason = models.CharField(max_length=500, blank=True)

    class Meta:
        permissions = [
            ("manage_certificates", "Manage certificate requests"),
            ("approve_certificates", "Approve and issue certificates"),
            ("view_all_certificates", "View all certificate records"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(student__isnull=False, employee__isnull=True)
                    | models.Q(student__isnull=True, employee__isnull=False)
                ),
                name="certificate_one_subject",
            )
        ]


class IssuedDocument(TimestampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request = models.OneToOneField(DocumentRequest, on_delete=models.PROTECT, related_name="issued")
    number = models.CharField(max_length=50, unique=True)
    verification_token = models.CharField(
        max_length=64, unique=True, default=verification_token, editable=False
    )
    issued_at = models.DateTimeField()
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    signatory = models.ForeignKey(Signatory, on_delete=models.PROTECT)
    snapshot = models.JSONField()
    state = models.CharField(
        max_length=16,
        default="valid",
        choices=[("valid", "Valid"), ("revoked", "Revoked"), ("replaced", "Replaced")],
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    revocation_reason = models.CharField(max_length=500, blank=True)
    replaces = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="replacement"
    )


class DocumentHistory(TimestampedModel):
    request = models.ForeignKey(DocumentRequest, on_delete=models.PROTECT, related_name="history")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    action = models.CharField(max_length=30)
    reason = models.CharField(max_length=500, blank=True)
