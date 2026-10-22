from .models import AuditEvent


def record_event(event, *, actor=None, target=""):
    """Never pass passwords, request bodies, tokens or personal details."""
    if actor is not None and not actor.is_authenticated:
        actor = None
    return AuditEvent.objects.create(event=event, actor=actor, target=str(target)[:128])
