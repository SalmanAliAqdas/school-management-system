from django.conf import settings
from django.db import models


class AuditEvent(models.Model):
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    event = models.CharField(max_length=64)
    target = models.CharField(max_length=128, blank=True)

    class Meta:
        ordering = ["-occurred_at", "-pk"]
        default_permissions = ("view",)
        indexes = [models.Index(fields=["event", "occurred_at"])]

    def __str__(self):
        return f"{self.event} · {self.occurred_at}"
