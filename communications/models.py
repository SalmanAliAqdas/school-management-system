from django.db import models

from core.models import TimestampedModel

AUDIENCES = [
    (x, x.title())
    for x in ["school", "administrators", "staff", "teachers", "students", "guardians"]
]
STATES = [(x, x.title()) for x in ["draft", "pending", "published", "cancelled"]]


class Publication(TimestampedModel):
    kind = models.CharField(
        max_length=16, choices=[("event", "Event"), ("announcement", "Announcement")]
    )
    title = models.CharField(max_length=160)
    body = models.TextField(max_length=16000)
    category = models.CharField(max_length=60, default="General")
    author = models.ForeignKey("accounts.User", on_delete=models.PROTECT)
    audience = models.CharField(max_length=20, choices=AUDIENCES, default="school")
    academic_year = models.ForeignKey(
        "academics.AcademicYear", on_delete=models.PROTECT, null=True, blank=True
    )
    section = models.ForeignKey(
        "academics.Section", on_delete=models.PROTECT, null=True, blank=True
    )
    publish_at = models.DateTimeField()
    expires_at = models.DateTimeField(null=True, blank=True)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    location = models.CharField(max_length=160, blank=True)
    state = models.CharField(max_length=12, choices=STATES, default="draft")
    pinned = models.BooleanField(default=False)
    important = models.BooleanField(default=False)
    cancellation_reason = models.CharField(max_length=500, blank=True)
    revision = models.PositiveIntegerField(default=1)

    class Meta:
        permissions = [
            ("manage_communications", "Manage events and announcements"),
            ("publish_communications", "Approve and publish communications"),
            ("moderate_messages", "Review reported messages"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(expires_at__isnull=True)
                | models.Q(expires_at__gt=models.F("publish_at")),
                name="publication_expiry",
            ),
            models.CheckConstraint(
                condition=models.Q(kind="announcement")
                | models.Q(
                    starts_at__isnull=False,
                    ends_at__isnull=False,
                    ends_at__gt=models.F("starts_at"),
                ),
                name="event_dates",
            ),
        ]

    def __str__(self):
        return self.title


class PublicationHistory(TimestampedModel):
    publication = models.ForeignKey(Publication, on_delete=models.PROTECT, related_name="history")
    actor = models.ForeignKey("accounts.User", on_delete=models.PROTECT)
    snapshot = models.JSONField(default=dict)


class PublicationRead(TimestampedModel):
    publication = models.ForeignKey(Publication, on_delete=models.PROTECT)
    user = models.ForeignKey("accounts.User", on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["publication", "user"], name="publication_read_once")
        ]


class Conversation(TimestampedModel):
    subject = models.CharField(max_length=160)
    student = models.ForeignKey("people.Student", on_delete=models.PROTECT, null=True, blank=True)
    initiator = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="started_conversations"
    )
    recipient = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="received_conversations"
    )
    blocked = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(initiator=models.F("recipient")),
                name="conversation_distinct_users",
            )
        ]


class Message(TimestampedModel):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.PROTECT, related_name="messages"
    )
    sender = models.ForeignKey("accounts.User", on_delete=models.PROTECT)
    body = models.TextField(max_length=10000)
    hidden = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "pk"]
        indexes = [models.Index(fields=["sender", "created_at"])]


class Document(TimestampedModel):
    publication = models.ForeignKey(
        Publication, on_delete=models.PROTECT, null=True, blank=True, related_name="documents"
    )
    message = models.ForeignKey(
        Message, on_delete=models.PROTECT, null=True, blank=True, related_name="documents"
    )
    filename = models.CharField(max_length=120)
    content_type = models.CharField(max_length=80)
    data = models.BinaryField()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(publication__isnull=False, message__isnull=True)
                | models.Q(publication__isnull=True, message__isnull=False),
                name="document_one_source",
            )
        ]


class Report(TimestampedModel):
    message = models.ForeignKey(Message, on_delete=models.PROTECT)
    reporter = models.ForeignKey(
        "accounts.User", on_delete=models.PROTECT, related_name="communication_reports"
    )
    reason = models.CharField(max_length=1000)
    resolution = models.CharField(max_length=1000, blank=True)
    reviewer = models.ForeignKey(
        "accounts.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviewed_communications",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["message", "reporter"], name="one_message_report")
        ]


class CommunicationPolicy(TimestampedModel):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    messages_per_hour = models.PositiveSmallIntegerField(default=30)
    retention_days = models.PositiveIntegerField(
        default=2555,
        help_text=(
            "Minimum retention; no automatic deletion. Legal holds and backups "
            "require operational review."
        ),
    )
    require_approval = models.BooleanField(default=True)


class Notice(TimestampedModel):
    recipient = models.ForeignKey("accounts.User", on_delete=models.PROTECT)
    student = models.ForeignKey("people.Student", on_delete=models.PROTECT, null=True, blank=True)
    category_name = models.CharField(max_length=20)
    key = models.CharField(max_length=160)
    title = models.CharField(max_length=200)
    url = models.CharField(max_length=250)
    publication = models.ForeignKey(Publication, on_delete=models.PROTECT, null=True, blank=True)
    assignment = models.ForeignKey(
        "learning.Assignment", on_delete=models.PROTECT, null=True, blank=True
    )
    timetable = models.ForeignKey(
        "scheduling.Timetable", on_delete=models.PROTECT, null=True, blank=True
    )
    conversation = models.ForeignKey(Conversation, on_delete=models.PROTECT, null=True, blank=True)
    available_at = models.DateTimeField()
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "key"], name="deduplicated_communication_notice"
            )
        ]
        indexes = [models.Index(fields=["recipient", "read_at", "available_at"])]
