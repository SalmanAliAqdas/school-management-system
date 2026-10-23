from django import template
from django.utils import timezone

from attendance.calendar import school_now
from communications.selectors import conversations, publications
from learning.selectors import visible as assignments
from scheduling.selectors import daily

register = template.Library()


@register.inclusion_tag("operations/activity.html", takes_context=True)
def school_activity(context):
    user = context["request"].user
    role = context.get("portal_role")
    personal = role if role in ("student", "parent") else None
    events = (
        publications(user, personal_role=personal)
        .filter(kind="event", starts_at__gte=timezone.now())
        .order_by("starts_at")[:3]
    )
    homework = (
        assignments(user, personal_role=personal)
        .filter(state="scheduled", due_at__gte=timezone.now())
        .order_by("due_at")[:3]
    )
    return {
        "events": events,
        "homework": homework,
        "lessons": daily(user, school_now().date(), personal_role=personal)[:4],
        "threads": conversations(user).count(),
    }
