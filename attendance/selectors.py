from django.db.models import Exists, OuterRef, Q

from academics.models import Section, TeachingAssignment
from people.models import Enrollment, Staff, Teacher
from people.selectors import enrollments_visible_to

from .models import (
    AbsenceNotification,
    AttendanceCorrection,
    LeaveRequest,
    StaffAttendance,
    StudentAttendance,
    StudentRegister,
)


def student_entries_visible_to(user, *, drafts=False):
    rows = StudentAttendance.objects.select_related(
        "student",
        "enrollment",
        "register__policy",
        "register__section__school_class",
        "register__academic_year",
    )
    if (
        not user.is_authenticated
        or not user.is_active
        or not user.has_perm("attendance.view_attendance")
    ):
        return rows.none()
    rows = rows.filter(enrollment__in=enrollments_visible_to(user))
    # Student/guardian dashboard access never reveals drafts, even if mixed with read capabilities.
    if not drafts or not user.has_perm("attendance.mark_attendance"):
        rows = rows.filter(register__state="final")
    return rows


def sections_markable_by(user, year):
    sections = Section.objects.select_related("school_class")
    if (
        not user.is_authenticated
        or not user.is_active
        or not user.has_perm("attendance.mark_attendance")
    ):
        return sections.none()
    if user.has_perms(
        ["attendance.view_all_attendance", "people.view_all_students", "people.view_student"]
    ):
        return sections
    if not user.has_perm("accounts.access_teacher_dashboard"):
        return sections.none()
    return sections.filter(
        teaching_assignments__teacher__user=user,
        teaching_assignments__academic_year=year,
        teaching_assignments__teacher__is_active=True,
    ).distinct()


def registers_visible_to(user):
    rows = StudentRegister.objects.select_related(
        "section__school_class", "academic_year", "policy", "submitted_by"
    )
    if (
        not user.is_authenticated
        or not user.is_active
        or not user.has_perm("attendance.mark_attendance")
    ):
        return rows.none()
    if user.has_perms(
        ["attendance.view_all_attendance", "people.view_all_students", "people.view_student"]
    ):
        return rows
    assigned = TeachingAssignment.objects.filter(
        teacher__user=user,
        academic_year_id=OuterRef("academic_year_id"),
        section_id=OuterRef("section_id"),
    )
    return (
        rows.alias(assigned=Exists(assigned)).filter(assigned=True)
        if user.has_perm("accounts.access_teacher_dashboard")
        else rows.none()
    )


def enrollment_roster(year, section, day):
    return (
        Enrollment.objects.filter(academic_year=year, section=section, started_on__lte=day)
        .filter(Q(ended_on__isnull=True) | Q(ended_on__gte=day))
        .select_related("student", "section__school_class")
        .order_by("roll_number", "student__first_name", "student_id")
    )


def staff_roster(day):
    bounds = Q(is_active=True, left_on__isnull=True) | Q(left_on__gte=day)
    teachers = Teacher.objects.filter(bounds, joined_on__lte=day).order_by("first_name", "pk")
    staff = (
        Staff.objects.filter(bounds, joined_on__lte=day)
        .exclude(user__isnull=False, user__teacher_profile__isnull=False)
        .order_by("first_name", "pk")
    )
    return [(f"teacher:{p.pk}", p) for p in teachers] + [(f"staff:{p.pk}", p) for p in staff]


def staff_entries_visible_to(user, *, drafts=False):
    rows = StaffAttendance.objects.select_related(
        "teacher", "staff", "register__policy", "register__academic_year"
    )
    if (
        not user.is_authenticated
        or not user.is_active
        or not user.has_perm("attendance.view_staff_attendance")
    ):
        return rows.none()
    if not user.has_perm("attendance.view_all_staff_attendance"):
        rows = rows.filter(Q(teacher__user=user) | Q(staff__user=user))
    if not drafts or not user.has_perm("attendance.manage_staff_attendance"):
        rows = rows.filter(register__state="final")
    return rows


def corrections_visible_to(user):
    return AttendanceCorrection.objects.filter(
        Q(student_entry__in=student_entries_visible_to(user))
        | Q(staff_entry__in=staff_entries_visible_to(user))
    ).select_related(
        "student_entry__student",
        "student_entry__register__policy",
        "staff_entry__teacher",
        "staff_entry__staff",
        "staff_entry__register__policy",
        "requested_by",
        "reviewed_by",
    )


def leaves_visible_to(user):
    rows = LeaveRequest.objects.select_related(
        "teacher", "staff", "academic_year", "requested_by", "reviewed_by"
    )
    if (
        not user.is_authenticated
        or not user.is_active
        or not user.has_perm("attendance.view_staff_attendance")
    ):
        return rows.none()
    return (
        rows
        if user.has_perm("attendance.view_all_staff_attendance")
        else rows.filter(Q(teacher__user=user) | Q(staff__user=user))
    )


def notifications_visible_to(user):
    rows = AbsenceNotification.objects.select_related(
        "entry__student", "entry__register__academic_year", "guardian"
    )
    if (
        not user.is_authenticated
        or not user.is_active
        or not user.has_perms(
            [
                "attendance.view_attendance",
                "accounts.access_parent_dashboard",
                "people.view_student",
            ]
        )
    ):
        return rows.none()
    return rows.filter(
        recipient=user, guardian__user=user, entry__student__guardian_links__guardian__user=user
    ).distinct()
