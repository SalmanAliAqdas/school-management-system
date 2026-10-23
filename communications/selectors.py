from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from scheduling.access import children, current_assignments, placements

from .models import Conversation, Publication


def staff(user):
    return user.is_active and (
        user.has_perm("accounts.access_admin_dashboard")
        or user.has_perm("accounts.access_teacher_dashboard")
    )


def pair_allowed(first, second, student=None):
    if not first.is_active or not second.is_active or first.pk == second.pk:
        return False
    # Student-only accounts cannot initiate arbitrary adult conversations.
    if student is None:
        return staff(first) and staff(second)
    for guardian, teacher in ((first, second), (second, first)):
        if not guardian.has_perm("accounts.access_parent_dashboard"):
            continue
        if (
            not children(guardian)
            .filter(pk=student.pk, guardian_links__guardian__user=guardian)
            .exists()
        ):
            continue
        for placement in placements(guardian).filter(student=student):
            if (
                current_assignments(teacher)
                .filter(academic_year=placement.academic_year, section=placement.section)
                .exists()
            ):
                return True
        if teacher.has_perm("communications.manage_communications"):
            return True
    return False


def conversations(user):
    candidates = Conversation.objects.filter(Q(initiator=user) | Q(recipient=user)).select_related(
        "initiator", "recipient", "student"
    )
    ids = [row.pk for row in candidates if pair_allowed(row.initiator, row.recipient, row.student)]
    return candidates.filter(pk__in=ids)


def recipients(user, student=None):
    return [
        other
        for other in get_user_model().objects.filter(is_active=True).exclude(pk=user.pk)
        if pair_allowed(user, other, student)
    ]


def publications(user, *, management=False, personal_role=None):
    rows = Publication.objects.all()
    if not user.is_authenticated or not user.is_active:
        return rows.none()
    if not personal_role and management and user.has_perm("communications.manage_communications"):
        return rows
    audience = ["school"]
    if not personal_role and staff(user):
        audience += ["staff"]
    for permission, label in [
        ("access_admin_dashboard", "administrators"),
        ("access_teacher_dashboard", "teachers"),
        ("access_student_dashboard", "students"),
        ("access_parent_dashboard", "guardians"),
    ]:
        if personal_role and permission != "access_" + personal_role + "_dashboard":
            continue
        if user.has_perm("accounts." + permission):
            audience.append(label)
    if len(audience) == 1:
        return rows.none()
    scoped = Q(academic_year__isnull=True, section__isnull=True)
    for year_id, section_id in (
        placements(user, role=personal_role)
        .values_list("academic_year_id", "section_id")
        .distinct()
    ):
        scoped |= Q(academic_year_id=year_id, section__isnull=True) | Q(
            academic_year_id=year_id, section_id=section_id
        )
    for year_id, section_id in (
        (current_assignments(user).none() if personal_role else current_assignments(user))
        .values_list("academic_year_id", "section_id")
        .distinct()
    ):
        scoped |= Q(academic_year_id=year_id, section__isnull=True) | Q(
            academic_year_id=year_id, section_id=section_id
        )
    if not personal_role and user.has_perm("communications.manage_communications"):
        scoped = Q()
    return rows.filter(
        scoped,
        audience__in=audience,
        state__in=["published", "cancelled"],
        publish_at__lte=timezone.now(),
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
