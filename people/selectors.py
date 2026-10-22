from django.db.models import Exists, OuterRef, Q

from academics.models import TeachingAssignment

from .models import Enrollment, Student


def has_global_student_access(user):
    return user.has_perm("people.view_all_students")


def enrollments_visible_to(user):
    queryset = Enrollment.objects.select_related("section__school_class", "academic_year")
    if not user.is_authenticated or not user.is_active or not user.has_perm("people.view_student"):
        return queryset.none()
    if has_global_student_access(user):
        return queryset
    scope = Q(pk__in=[])
    if user.has_perm("accounts.access_student_dashboard"):
        scope |= Q(student__user=user)
    if user.has_perm("accounts.access_parent_dashboard"):
        scope |= Q(student__guardian_links__guardian__user=user)
    if user.has_perm("accounts.access_teacher_dashboard"):
        assigned = TeachingAssignment.objects.filter(
            teacher__user=user,
            section_id=OuterRef("section_id"),
            academic_year_id=OuterRef("academic_year_id"),
        )
        queryset = queryset.alias(assigned_to_viewer=Exists(assigned))
        scope |= Q(assigned_to_viewer=True)
    return queryset.filter(scope).distinct()


def students_visible_to(user):
    queryset = Student.objects.all()
    if not user.is_authenticated or not user.is_active or not user.has_perm("people.view_student"):
        return queryset.none()
    if has_global_student_access(user):
        return queryset
    scope = Q(pk__in=[])
    if user.has_perm("accounts.access_student_dashboard"):
        scope |= Q(user=user)
    if user.has_perm("accounts.access_parent_dashboard"):
        scope |= Q(guardian_links__guardian__user=user)
    if user.has_perm("accounts.access_teacher_dashboard"):
        scope |= Q(pk__in=enrollments_visible_to(user).values("student_id"))
    return queryset.filter(scope).distinct()
