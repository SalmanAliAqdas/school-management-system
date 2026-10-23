from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from people.models import Enrollment
from scheduling.access import children, current_assignments

from .models import Assignment, Submission


def visible(user, personal_role=None):
    rows = Assignment.objects.select_related(
        "teaching__academic_year",
        "teaching__section__school_class",
        "teaching__subject",
        "teaching__teacher",
    )
    if not personal_role and user.has_perm("learning.manage_learning"):
        return rows
    placements = Enrollment.objects.filter(
        student__in=children(user, personal_role),
        academic_year_id=OuterRef("teaching__academic_year_id"),
        section_id=OuterRef("teaching__section_id"),
        started_on__lte=OuterRef("publish_at__date"),
    ).filter(Q(ended_on__isnull=True) | Q(ended_on__gte=OuterRef("publish_at__date")))
    return rows.alias(eligible=Exists(placements)).filter(
        (Q(pk__in=[]) if personal_role else Q(teaching__in=current_assignments(user)))
        | Q(
            eligible=True,
            state__in=["scheduled", "closed", "archived"],
            publish_at__lte=timezone.now(),
        )
    )


def can_review(user, assignment):
    return (
        user.has_perm("learning.manage_learning")
        or current_assignments(user).filter(pk=assignment.teaching_id).exists()
    )


def submissions(user, assignment):
    rows = Submission.objects.filter(assignment=assignment).select_related("student")
    return rows if can_review(user, assignment) else rows.filter(student__in=children(user))


def roster(assignment):
    day = assignment.publish_at.date()
    return (
        Enrollment.objects.filter(
            academic_year=assignment.teaching.academic_year,
            section=assignment.teaching.section,
            started_on__lte=day,
        )
        .filter(Q(ended_on__isnull=True) | Q(ended_on__gte=day))
        .select_related("student")
    )
