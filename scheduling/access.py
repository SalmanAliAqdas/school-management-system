from django.core.exceptions import PermissionDenied
from django.db.models import Q

from academics.models import TeachingAssignment
from attendance.calendar import school_now
from people.models import Enrollment, Student


def require(user, permission):
    if not user.is_authenticated or not user.is_active or not user.has_perm(permission):
        raise PermissionDenied


def children(user, role=None):
    scope = Q(pk__in=[])
    if role in (None, "student") and user.has_perm("accounts.access_student_dashboard"):
        scope |= Q(user=user)
    if role in (None, "parent") and user.has_perm("accounts.access_parent_dashboard"):
        scope |= Q(guardian_links__guardian__user=user)
    return Student.objects.filter(scope).distinct()


def current_assignments(user):
    day = school_now().date()
    rows = TeachingAssignment.objects.filter(
        teacher__user=user,
        teacher__is_active=True,
        teacher__joined_on__lte=day,
        academic_year__status="open",
        academic_year__starts_on__lte=day,
        academic_year__ends_on__gte=day,
    ).filter(Q(teacher__left_on__isnull=True) | Q(teacher__left_on__gte=day))
    return rows if user.has_perm("accounts.access_teacher_dashboard") else rows.none()


def placements(user, day=None, role=None):
    day = day or school_now().date()
    return Enrollment.objects.filter(student__in=children(user, role), started_on__lte=day).filter(
        Q(ended_on__isnull=True) | Q(ended_on__gte=day)
    )


def selected_child(request):
    from django.core.exceptions import ValidationError
    from django.http import Http404
    from django.shortcuts import get_object_or_404

    value = request.GET.get("child")
    if not value:
        return None
    try:
        return get_object_or_404(children(request.user), pk=value)
    except (ValidationError, ValueError) as exc:
        raise Http404 from exc
