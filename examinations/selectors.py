from django.db.models import Exists, OuterRef, Q

from academics.models import TeachingAssignment
from people.models import Student

from .models import (
    CandidateAmendment,
    ExamCandidate,
    ExamNotification,
    ExamSession,
    ExamSubject,
    MarkSheet,
    PublishedResult,
    ResultCorrection,
)


def capable(user, codename):
    return user.is_authenticated and user.is_active and user.has_perm(f"examinations.{codename}")


def can_oversee(user, session):
    if not capable(user, "view_examinations"):
        return False
    return capable(user, "view_all_examinations") or (
        (capable(user, "review_results") or capable(user, "manage_examinations"))
        and session.controllers.filter(pk=user.pk).exists()
    )


def personal_students(user):
    students = Student.objects.all()
    if not capable(user, "view_examinations"):
        return students.none()
    scope = Q(pk__in=[])
    if user.has_perm("accounts.access_student_dashboard"):
        scope |= Q(user=user)
    if user.has_perm("accounts.access_parent_dashboard"):
        scope |= Q(guardian_links__guardian__user=user)
    return students.filter(scope).distinct()


def sessions_visible_to(user):
    sessions = ExamSession.objects.select_related(
        "academic_year", "term", "policy", "assessment_type"
    )
    if not capable(user, "view_examinations"):
        return sessions.none()
    if capable(user, "view_all_examinations"):
        return sessions
    scope = Q(candidates__student__in=personal_students(user)) & ~Q(state="draft")
    if capable(user, "review_results") or capable(user, "manage_examinations"):
        scope |= Q(controllers=user)
    if capable(user, "enter_marks") and user.has_perm("accounts.access_teacher_dashboard"):
        scope |= Q(cohorts__subjects__in=authorized_subjects(user)) & ~Q(state="draft")
    return sessions.filter(scope).distinct()


def authorized_subjects(user):
    subjects = ExamSubject.objects.select_related(
        "cohort__section__school_class", "cohort__session__policy", "subject"
    )
    if not capable(user, "view_examinations"):
        return subjects.none()
    if capable(user, "view_all_examinations"):
        return subjects
    scope = Q(pk__in=[])
    if capable(user, "review_results") or capable(user, "manage_examinations"):
        scope |= Q(cohort__session__controllers=user)
    if capable(user, "enter_marks") and user.has_perm("accounts.access_teacher_dashboard"):
        assignment = TeachingAssignment.objects.filter(
            teacher__user=user,
            teacher__is_active=True,
            academic_year_id=OuterRef("cohort__session__academic_year_id"),
            section_id=OuterRef("cohort__section_id"),
            subject_id=OuterRef("subject_id"),
        )
        subjects = subjects.alias(assigned=Exists(assignment))
        scope |= Q(assigned=True) & ~Q(cohort__session__state="draft")
    return subjects.filter(scope).distinct()


def subjects_visible_to(user, session):
    return authorized_subjects(user).filter(cohort__session=session)


def sheets_visible_to(user):
    rows = MarkSheet.objects.filter(
        assessment__exam_subject__in=authorized_subjects(user)
    ).select_related(
        "assessment__exam_subject__cohort__session__policy",
        "assessment__exam_subject__cohort__section__school_class",
        "assessment__exam_subject__subject",
    )
    return rows


def candidates_visible_to(user):
    rows = ExamCandidate.objects.select_related(
        "student", "enrollment", "session__policy", "cohort__section__school_class"
    )
    if not capable(user, "view_examinations"):
        return rows.none()
    scope = Q(student__in=personal_students(user)) & Q(session__state__in=["published", "archived"])
    if capable(user, "view_all_examinations"):
        return rows
    if capable(user, "review_results") or capable(user, "manage_examinations"):
        scope |= Q(session__controllers=user)
    return rows.filter(scope).distinct()


def results_visible_to(user):
    return PublishedResult.objects.filter(candidate__in=candidates_visible_to(user)).select_related(
        "publication__session", "candidate__student", "candidate__cohort__section__school_class"
    )


def corrections_visible_to(user):
    return ResultCorrection.objects.filter(entry__sheet__in=sheets_visible_to(user)).select_related(
        "entry__candidate__student",
        "entry__sheet__assessment__exam_subject__cohort__session",
        "requested_by",
        "reviewed_by",
    )


def amendments_visible_to(user):
    rows = CandidateAmendment.objects.select_related(
        "candidate__student", "candidate__session", "requested_by", "reviewed_by"
    )
    scope = Q(pk__in=[])
    if capable(user, "view_all_examinations"):
        return rows
    if capable(user, "review_results") or capable(user, "manage_examinations"):
        scope |= Q(candidate__session__controllers=user)
    return rows.filter(scope)


def notifications_visible_to(user):
    rows = ExamNotification.objects.filter(recipient=user).select_related(
        "event__session", "candidate__student"
    )
    sessions = sessions_visible_to(user)
    candidates = candidates_visible_to(user)
    return rows.filter(
        Q(candidate__isnull=True, event__session__in=sessions) | Q(candidate__in=candidates)
    ).distinct()
