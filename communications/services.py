from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from audit.services import record_event
from learning.uploads import read_private_upload
from scheduling.access import require

from .models import (
    CommunicationPolicy,
    Conversation,
    Document,
    Message,
    Publication,
    PublicationHistory,
    Report,
)
from .selectors import conversations, pair_allowed


@transaction.atomic
def save_publication(actor, row, expected=None, files=()):
    require(actor, "communications.manage_communications")
    old = Publication.objects.select_for_update().filter(pk=row.pk).first() if row.pk else None
    if old:
        if old.revision != expected:
            raise ValidationError("This publication changed. Reload before editing.")
        if old.state in ("published", "cancelled"):
            require(actor, "communications.publish_communications")
        row.state, row.author = old.state, old.author
        row.revision = old.revision + 1
    else:
        row.state, row.author = "draft", actor
    if row.section_id and not row.academic_year_id:
        raise ValidationError("Section targeting requires an academic year.")
    if row.kind == "event" and (
        not row.starts_at or not row.ends_at or row.ends_at <= row.starts_at
    ):
        raise ValidationError("Events require ordered start and end times.")
    row.full_clean()
    uploads = [read_private_upload(f) for f in files]
    if len(uploads) + (old.documents.count() if old else 0) > 5:
        raise ValidationError("At most five attachments are allowed.")
    row.save()
    for upload in uploads:
        Document.objects.create(publication=row, **upload)
    publication_history(actor, row)
    if row.state == "published":
        from .notices import publication_notice

        publication_notice(row)
    return row


def publication_history(actor, row):
    PublicationHistory.objects.create(
        publication=row,
        actor=actor,
        snapshot={
            "title": row.title,
            "body": row.body,
            "state": row.state,
            "audience": row.audience,
            "starts_at": str(row.starts_at),
            "ends_at": str(row.ends_at),
            "reason": row.cancellation_reason,
            "revision": row.revision,
        },
    )
    record_event("communications.publication", actor=actor, target=row.pk)


@transaction.atomic
def publication_action(actor, pk, action, reason=""):
    require(actor, "communications.manage_communications")
    row = Publication.objects.select_for_update().get(pk=pk)
    policy = CommunicationPolicy.objects.first()
    if action == "submit" and row.state == "draft":
        row.state = "pending"
    elif action == "publish" and row.state in ("draft", "pending"):
        require(actor, "communications.publish_communications")
        if (policy is None or policy.require_approval) and row.author_id == actor.pk:
            raise ValidationError("A different authorized publisher must approve this publication.")
        row.state = "published"
    elif action == "cancel" and row.state == "published" and reason.strip():
        require(actor, "communications.publish_communications")
        row.state, row.cancellation_reason = "cancelled", reason
    else:
        raise ValidationError("Invalid action or missing cancellation reason.")
    row.revision += 1
    row.full_clean()
    row.save()
    publication_history(actor, row)
    from .notices import publication_notice

    publication_notice(row)
    return row


@transaction.atomic
def send(actor, body, *, conversation=None, recipient=None, student=None, subject="", files=()):
    # User row serialization makes the throttle robust to concurrent requests.
    actor = get_user_model().objects.select_for_update().get(pk=actor.pk)
    if conversation:
        row = conversations(actor).filter(pk=conversation).first()
        if not row:
            raise PermissionDenied
        row = Conversation.objects.select_for_update().get(pk=row.pk)
    else:
        if not recipient or not pair_allowed(actor, recipient, student):
            raise PermissionDenied
        if not subject.strip():
            raise ValidationError("A conversation subject is required.")
        row = Conversation(subject=subject, student=student, initiator=actor, recipient=recipient)
        row.full_clean()
        row.save()
    if row.blocked or not pair_allowed(row.initiator, row.recipient, row.student):
        raise PermissionDenied
    policy = CommunicationPolicy.objects.first()
    limit = policy.messages_per_hour if policy else 30
    recent = Message.objects.filter(
        sender=actor, created_at__gte=timezone.now() - timedelta(hours=1)
    )
    if recent.count() >= limit:
        raise ValidationError("Message limit reached. Please try again later.")
    if not body.strip() or len(body) > 10000:
        raise ValidationError("Enter a message of 1–10,000 characters.")
    if recent.filter(
        conversation=row, body=body, created_at__gte=timezone.now() - timedelta(minutes=1)
    ).exists():
        raise ValidationError("This message was just sent; refresh before retrying.")
    uploads = [read_private_upload(f) for f in files]
    if len(uploads) > 3:
        raise ValidationError("At most three attachments per message.")
    message = Message.objects.create(conversation=row, sender=actor, body=body)
    for upload in uploads:
        Document.objects.create(message=message, **upload)
    record_event("communications.message", actor=actor, target=message.pk)
    from .notices import message_notice

    message_notice(message)
    return row


@transaction.atomic
def report_message(actor, pk, reason):
    message = Message.objects.get(pk=pk)
    if not conversations(actor).filter(pk=message.conversation_id).exists():
        raise PermissionDenied
    if not reason.strip():
        raise ValidationError("Explain the concern.")
    row = Report(message=message, reporter=actor, reason=reason)
    row.full_clean()
    row.save()
    record_event("communications.report", actor=actor, target=row.pk)
    return row


@transaction.atomic
def moderate(actor, pk, resolution, hide=False, block=False):
    require(actor, "communications.moderate_messages")
    report = Report.objects.select_for_update().get(pk=pk)
    if report.reviewer_id or not resolution.strip():
        raise ValidationError("A report needs a reasoned, single moderation decision.")
    report.resolution, report.reviewer = resolution, actor
    report.full_clean()
    report.save()
    if hide:
        Message.objects.filter(pk=report.message_id).update(hidden=True)
    if block:
        Conversation.objects.filter(pk=report.message.conversation_id).update(blocked=True)
    record_event("communications.moderation", actor=actor, target=report.pk)
    return report
