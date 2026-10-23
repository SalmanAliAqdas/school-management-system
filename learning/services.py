from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from audit.services import record_event
from scheduling.access import require

from .models import (
    Assignment,
    AssignmentChange,
    Attachment,
    Feedback,
    Submission,
    SubmissionVersion,
)
from .selectors import can_review, roster
from .uploads import read_private_upload


def authorize(actor, assignment):
    if not actor.is_active or not can_review(actor, assignment):
        raise PermissionDenied
    year = assignment.teaching.academic_year
    from attendance.calendar import school_now

    if year.status != "open" or not year.starts_on <= school_now().date() <= year.ends_on:
        raise ValidationError("Historical assignments are read-only.")


def change(actor, assignment, action):
    AssignmentChange.objects.create(
        assignment=assignment,
        actor=actor,
        action=action,
        snapshot={
            "title": assignment.title,
            "description": assignment.description,
            "due_at": assignment.due_at.isoformat(),
            "state": assignment.state,
            "revision": assignment.revision,
        },
    )
    record_event("learning." + action, actor=actor, target=assignment.pk)


@transaction.atomic
def save_assignment(actor, assignment, expected=None, files=()):
    authorize(actor, assignment)
    if not assignment.teaching.is_active:
        raise ValidationError("This teaching assignment has been revoked.")
    old = (
        Assignment.objects.select_for_update().filter(pk=assignment.pk).first()
        if assignment.pk
        else None
    )
    if old:
        if old.revision != expected or old.state in ("closed", "archived"):
            raise ValidationError("Reload the assignment; it changed or is closed.")
        if old.teaching_id != assignment.teaching_id:
            raise ValidationError("Teaching scope cannot change.")
        if old.submissions.exists() and any(
            getattr(old, f) != getattr(assignment, f)
            for f in ("maximum", "rubric", "late_penalty", "publish_at", "submission_required")
        ):
            raise ValidationError("Assessment rules are frozen after submissions exist.")
        assignment.state = old.state
        assignment.revision = old.revision + 1
    else:
        assignment.state = "draft"
    assignment.full_clean()
    year = assignment.teaching.academic_year
    if (
        not year.starts_on
        <= assignment.publish_at.date()
        <= assignment.due_at.date()
        <= year.ends_on
    ):
        raise ValidationError("Assignment dates must fall inside its academic year.")
    if not isinstance(assignment.rubric, dict) or any(
        not isinstance(v, (int, float)) or v <= 0 for v in assignment.rubric.values()
    ):
        raise ValidationError("Rubric must map criterion names to positive numeric marks.")
    if assignment.rubric and (
        assignment.maximum is None
        or sum(Decimal(str(v)) for v in assignment.rubric.values()) != assignment.maximum
    ):
        raise ValidationError("Rubric criteria must total the maximum marks.")
    uploads = [read_private_upload(f) for f in files]
    if len(uploads) + (old.attachments.filter(version__isnull=True).count() if old else 0) > 5:
        raise ValidationError("At most five supporting files are allowed.")
    assignment.save()
    for upload in uploads:
        Attachment.objects.create(assignment=assignment, **upload)
    change(actor, assignment, "updated" if old else "created")
    if old and old.state == "scheduled":
        from communications.notices import learning_notice

        learning_notice(assignment, "updated")
    return assignment


@transaction.atomic
def transition(actor, pk, action):
    assignment = (
        Assignment.objects.select_for_update().select_related("teaching__academic_year").get(pk=pk)
    )
    authorize(actor, assignment)
    transitions = {
        ("draft", "publish"): "scheduled",
        ("scheduled", "close"): "closed",
        ("closed", "reopen"): "scheduled",
        ("closed", "archive"): "archived",
    }
    state = transitions.get((assignment.state, action))
    if not state:
        raise ValidationError("Invalid assignment transition.")
    assignment.state = state
    assignment.revision += 1
    assignment.save()
    change(actor, assignment, action)
    from communications.notices import learning_notice

    learning_notice(assignment, action)
    return assignment


@transaction.atomic
def submit(actor, pk, text, *, final, expected=0, files=()):
    require(actor, "accounts.access_student_dashboard")
    assignment = (
        Assignment.objects.select_for_update().select_related("teaching__academic_year").get(pk=pk)
    )
    from attendance.calendar import school_now

    now = school_now()

    year = assignment.teaching.academic_year
    if year.status != "open" or not year.starts_on <= school_now().date() <= year.ends_on:
        raise ValidationError("Historical assignments are closed for submission.")
    placement = roster(assignment).filter(student__user=actor).first()
    if not placement:
        raise PermissionDenied
    # Current placement is checked as well as the original published audience.
    from scheduling.access import placements

    if (
        not placements(actor)
        .filter(
            student=placement.student,
            section=assignment.teaching.section,
            academic_year=assignment.teaching.academic_year,
        )
        .exists()
    ):
        raise PermissionDenied
    if (
        assignment.state != "scheduled"
        or now < assignment.publish_at
        or not assignment.submission_required
    ):
        raise ValidationError("This assignment is not open for submissions.")
    late = now > assignment.due_at
    row, _ = Submission.objects.get_or_create(assignment=assignment, student=placement.student)
    if row.revision != expected or row.state not in ("draft", "returned"):
        raise ValidationError(
            "Submission changed or is already final; a revision request is required."
        )
    if late and not assignment.late_allowed and row.state != "returned":
        raise ValidationError("The submission deadline has passed.")
    uploads = [read_private_upload(f) for f in files]
    if len(uploads) > 5 or (final and not text.strip() and not uploads):
        raise ValidationError("Provide text or up to five attachments.")
    if len(text) > 20000:
        raise ValidationError("Submission text is too long.")
    row.revision += 1
    row.state = "submitted" if final else "draft"
    row.save()
    version = SubmissionVersion.objects.create(
        submission=row, number=row.revision, text=text, final=final, late=late
    )
    for upload in uploads:
        Attachment.objects.create(assignment=assignment, version=version, **upload)
    record_event("learning.submission", actor=actor, target=version.pk)
    return row


@transaction.atomic
def review(
    actor,
    pk,
    *,
    text,
    outcome,
    marks=None,
    released=False,
    guardian_visible=False,
    criterion_marks=None,
):
    row = Submission.objects.select_related("assignment").get(pk=pk)
    assignment = (
        Assignment.objects.select_for_update()
        .select_related("teaching__academic_year")
        .get(pk=row.assignment_id)
    )
    row.refresh_from_db()
    authorize(actor, assignment)
    if row.state == "draft" and outcome != "excused":
        raise ValidationError("A student draft cannot be reviewed.")
    if outcome not in ("reviewed", "graded", "returned", "excused"):
        raise ValidationError("Choose a valid review outcome.")
    if marks is not None and (
        assignment.maximum is None or not Decimal(0) <= marks <= assignment.maximum
    ):
        raise ValidationError("Marks must be within the assignment maximum.")
    if outcome == "graded" and marks is None:
        raise ValidationError("Enter marks for graded work.")
    criteria = criterion_marks or {}
    if assignment.rubric and outcome == "graded":
        if set(criteria) != set(assignment.rubric) or any(
            not Decimal(0) <= Decimal(str(criteria[k])) <= Decimal(str(v))
            for k, v in assignment.rubric.items()
        ):
            raise ValidationError("Complete the rubric within its criterion maxima.")
        if sum(Decimal(str(v)) for v in criteria.values()) != marks:
            raise ValidationError("Rubric marks must equal the awarded marks.")
    version = row.versions.first()
    if marks is not None and version and version.late:
        marks = (marks * (1 - assignment.late_penalty / 100)).quantize(Decimal(".01"))
    feedback = Feedback(
        submission=row,
        version=version,
        actor=actor,
        text=text,
        outcome=outcome,
        marks=marks,
        released=released,
        guardian_visible=guardian_visible,
        criterion_marks=criteria,
    )
    feedback.full_clean()
    feedback.save()
    if released:
        row.state = outcome
        row.save()
        from communications.notices import learning_notice

        learning_notice(assignment, "feedback", row)
    record_event("learning.feedback", actor=actor, target=feedback.pk)
    return feedback


@transaction.atomic
def excuse(actor, pk, student_id, reason):
    assignment = Assignment.objects.select_for_update().get(pk=pk)
    authorize(actor, assignment)
    placement = roster(assignment).filter(student_id=student_id).first()
    if not placement:
        raise PermissionDenied
    row, _ = Submission.objects.get_or_create(assignment=assignment, student=placement.student)
    return review(
        actor, row.pk, text=reason, outcome="excused", released=True, guardian_visible=True
    )
