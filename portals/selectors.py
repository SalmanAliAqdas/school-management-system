"""Presentation scopes narrow domain selectors; switching roles never expands them."""

from django.core.exceptions import PermissionDenied
from django.db.models import Exists, F, OuterRef, Q

from academics.models import AcademicYear, TeachingAssignment
from attendance.calendar import school_now
from examinations.selectors import sheets_visible_to
from people.models import Enrollment, Student
from people.selectors import students_visible_to

ROLES = {
    "student": ("Student", "accounts.access_student_dashboard"),
    "parent": ("Guardian", "accounts.access_parent_dashboard"),
    "teacher": ("Teaching", "accounts.access_teacher_dashboard"),
}


def require_role(user, role):
    if (
        role not in ROLES
        or not user.is_authenticated
        or not user.is_active
        or not user.has_perm(ROLES[role][1])
    ):
        raise PermissionDenied


def personal_students(user, role):
    require_role(user, role)
    rows = students_visible_to(user)
    if role == "student":
        return rows.filter(user=user)
    if role == "parent":
        return rows.filter(guardian_links__guardian__user=user).distinct()
    return rows.none()


def personal_finance_students(user, role):
    from finance.common import config
    from finance.selectors import students_visible_to as finance_students

    policy = config()
    rows = finance_students(user)
    enabled = policy and (
        (role == "student" and policy.student_portal)
        or (role == "parent" and policy.guardian_portal)
    )
    if not enabled:
        return rows.none()
    return rows.filter(pk__in=personal_students(user, role))


def assignments(user):
    require_role(user, "teacher")
    # Historical reads require actual employment overlap, not another role's global scope.
    return (
        TeachingAssignment.objects.filter(teacher__user=user)
        .filter(
            teacher__joined_on__lte=F("academic_year__ends_on"),
        )
        .filter(
            Q(teacher__left_on__isnull=True)
            | Q(teacher__left_on__gte=F("academic_year__starts_on"))
        )
        .select_related("teacher", "academic_year", "section__school_class", "subject")
    )


def assignment_writable(assignment, today=None):
    today = today or school_now().date()
    year, teacher = assignment.academic_year, assignment.teacher
    return (
        year.status == "open"
        and year.starts_on <= today <= year.ends_on
        and teacher.is_active
        and teacher.joined_on <= today
        and (teacher.left_on is None or teacher.left_on >= today)
    )


def assignment_roster(assignment, *, historical=False):
    rows = Enrollment.objects.filter(
        academic_year=assignment.academic_year, section=assignment.section
    ).select_related("student", "academic_year", "section__school_class")
    teacher = assignment.teacher
    rows = rows.filter(Q(ended_on__isnull=True) | Q(ended_on__gte=teacher.joined_on))
    if teacher.left_on:
        rows = rows.filter(started_on__lte=teacher.left_on)
    if not historical:
        day = school_now().date()
        rows = rows.filter(started_on__lte=day).filter(
            Q(ended_on__isnull=True) | Q(ended_on__gte=day)
        )
    latest = rows.order_by("student_id", "-started_on", "-pk").distinct("student_id").values("pk")
    rows = rows.filter(pk__in=latest)
    return rows.order_by("student__first_name", "student__last_name", "pk")


def teacher_sheets(user, scoped_assignments):
    match = scoped_assignments.filter(
        academic_year_id=OuterRef("assessment__exam_subject__cohort__session__academic_year_id"),
        section_id=OuterRef("assessment__exam_subject__cohort__section_id"),
        subject_id=OuterRef("assessment__exam_subject__subject_id"),
    )
    return sheets_visible_to(user).alias(portal_assigned=Exists(match)).filter(portal_assigned=True)


def student_years(student):
    return AcademicYear.objects.filter(enrollments__student=student).distinct()


def teacher_students(user):
    matched = assignments(user).filter(
        academic_year_id=OuterRef("academic_year_id"), section_id=OuterRef("section_id")
    )
    placements = Enrollment.objects.alias(assigned=Exists(matched)).filter(assigned=True)
    return Student.objects.filter(enrollments__in=placements).distinct()
