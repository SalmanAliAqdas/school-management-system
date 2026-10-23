from django.db.models import Count, F, Q
from django.utils import timezone

from .selectors import roster, submissions, visible


def assignment_report(user, assignment):
    rows = submissions(user, assignment)
    totals = rows.aggregate(
        submitted=Count("pk", filter=Q(state__in=["submitted", "reviewed", "graded", "returned"])),
        reviewed=Count("pk", filter=Q(state__in=["reviewed", "graded"])),
        excused=Count("pk", filter=Q(state="excused")),
    )
    expected = roster(assignment).count()
    totals["expected"] = expected
    totals["missing"] = (
        max(0, expected - totals["submitted"] - totals["excused"])
        if timezone.now() > assignment.due_at and assignment.submission_required
        else 0
    )
    totals["completion"] = (
        round(totals["submitted"] * 100 / (expected - totals["excused"]), 1)
        if expected > totals["excused"]
        else None
    )
    totals["late"] = rows.filter(
        versions__number=F("revision"), versions__late=True, versions__final=True
    ).count()
    totals["assignment"] = assignment
    return totals


def reports(user):
    from .selectors import can_review

    return [
        assignment_report(user, row)
        for row in visible(user).exclude(state="draft").order_by("-publish_at")[:100]
        if can_review(user, row)
    ]
