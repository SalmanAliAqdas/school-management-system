"""A bounded SQL read-side union. Source rows and their read history stay in place."""

from django.db.models import CharField, Value
from django.urls import reverse
from django.utils import timezone

from attendance.selectors import notifications_visible_to as attendance_notices
from communications.notices import visible as communication_notices
from examinations.selectors import notifications_visible_to as examination_notices
from finance.selectors import notices_visible_to as finance_notices

SOURCES = {
    "communications": lambda user: communication_notices(user).filter(
        category_name="communications"
    ),
    "learning": lambda user: communication_notices(user).filter(category_name="learning"),
    "scheduling": lambda user: communication_notices(user).filter(category_name="scheduling"),
    "attendance": attendance_notices,
    "examinations": examination_notices,
    "finance": finance_notices,
    **{
        name: (
            lambda user, category=name: communication_notices(user).filter(category_name=category)
        )
        for name in ("hr", "payroll", "library", "transport", "inventory", "certificates")
    },
}


def sources(user):
    result = {
        name: selector(user)
        for name, selector in SOURCES.items()
        if name
        not in (
            "communications",
            "learning",
            "scheduling",
            "hr",
            "payroll",
            "library",
            "transport",
            "inventory",
            "certificates",
        )
    }
    new_notices = communication_notices(user)
    result.update(
        {
            name: new_notices.filter(category_name=name)
            for name in (
                "communications",
                "learning",
                "scheduling",
                "hr",
                "payroll",
                "library",
                "transport",
                "inventory",
                "certificates",
            )
        }
    )
    return result


def inbox(user, *, category="", unread=False, child=None):
    parts = []
    for name, rows in sources(user).items():
        if category and name != category:
            continue
        if unread:
            rows = rows.filter(read_at__isnull=True)
        if child:
            field = {
                "attendance": "entry__student",
                "examinations": "candidate__student",
                "finance": "student",
                "communications": "student",
                "learning": "student",
                "scheduling": "student",
                "hr": "student",
                "payroll": "student",
                "library": "student",
                "transport": "student",
                "inventory": "student",
                "certificates": "student",
            }[name]
            rows = rows.filter(**{field: child})
        parts.append(
            rows.order_by()
            .annotate(category=Value(name, output_field=CharField()))
            .values("pk", "created_at", "read_at", "category")
        )
    if not parts:
        return inbox(user, category="attendance").none()
    return parts[0].union(*parts[1:]).order_by("-created_at", "category", "pk")


def unread_count(user):
    return sum(rows.filter(read_at__isnull=True).count() for rows in sources(user).values())


def hydrate(user, page):
    records = list(page.object_list)
    objects = {}
    for category, rows in sources(user).items():
        ids = [r["pk"] for r in records if r["category"] == category]
        if ids:
            objects[category] = {row.pk: row for row in rows.filter(pk__in=ids)}
    notices = []
    for record in records:
        category = record["category"]
        row = objects.get(category, {}).get(record["pk"])
        if row is None:
            continue  # A revoked link between union and hydration fails closed.
        child, title, url = None, "", ""
        if category == "attendance":
            child = row.entry.student
            title = f"{row.entry.attendance_on}: recorded absence ({row.get_state_display()})"
            url = reverse("attendance:student", args=[child.pk])
        elif category == "examinations":
            child = row.candidate.student if row.candidate_id else None
            title = f"{row.event.label} · {row.event.session.name}"
            url = (
                reverse("examinations:candidate", args=[row.candidate_id])
                if child
                else (reverse("examinations:session", args=[row.event.session_id]))
            )
        elif category in (
            "communications",
            "learning",
            "scheduling",
            "hr",
            "payroll",
            "library",
            "transport",
            "inventory",
            "certificates",
        ):
            child, title, url = row.student, row.title, row.url
        else:
            child = row.student
            title = row.kind.replace("_", " ").capitalize()
            url = (
                reverse("finance:invoice", args=[row.invoice_id])
                if row.invoice_id
                else reverse("finance:receipt", args=[row.payment_id])
                if row.payment_id
                else reverse("finance:student", args=[child.pk])
            )
        notices.append({**record, "child": child, "title": title, "url": url})
    page.object_list = notices
    return page


def mark_read(user, category, pk):
    from django.http import Http404
    from django.shortcuts import get_object_or_404

    if category not in SOURCES:
        raise Http404
    rows = SOURCES[category](user)
    row = get_object_or_404(rows, pk=pk)
    # Repeat the scoped filter for the actual mutation, including current guardian links.
    return rows.filter(pk=row.pk, read_at__isnull=True).update(
        read_at=timezone.now(), updated_at=timezone.now()
    )
