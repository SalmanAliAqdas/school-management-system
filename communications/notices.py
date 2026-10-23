from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from people.models import GuardianStudent

from .models import Notice


def add(user_id, key, title, url, **kwargs):
    if user_id:
        Notice.objects.get_or_create(
            recipient_id=user_id,
            key=key,
            defaults={
                "title": title[:200],
                "url": url,
                "available_at": kwargs.pop("available_at", timezone.now()),
                **kwargs,
            },
        )


def family(student):
    return [
        student.user_id,
        *GuardianStudent.objects.filter(student=student).values_list(
            "guardian__user_id", flat=True
        ),
    ]


def learning_notice(assignment, action, submission=None):
    from learning.selectors import roster

    children = [submission.student] if submission else [p.student for p in roster(assignment)]
    feedback_id = submission.feedback.first().pk if submission else 0
    for child in children:
        for user in family(child):
            add(
                user,
                (
                    f"learning:{assignment.pk}:{assignment.revision}:{action}:"
                    f"{submission.pk if submission else child.pk}:{feedback_id}"
                ),
                f"{assignment.title}: {action}",
                reverse("learning:detail", args=[assignment.pk]),
                category_name="learning",
                assignment=assignment,
                student=child,
                available_at=max(assignment.publish_at, timezone.now()),
            )
            if action in ("publish", "updated", "reopen"):
                add(
                    user,
                    f"due:{assignment.pk}:{assignment.revision}:{child.pk}",
                    f"Due soon: {assignment.title}",
                    reverse("learning:detail", args=[assignment.pk]),
                    category_name="learning",
                    assignment=assignment,
                    student=child,
                    available_at=max(assignment.publish_at, assignment.due_at - timedelta(days=1)),
                )


def schedule_notice(table, action, substitution=None):
    from people.models import Enrollment

    students = (
        Enrollment.objects.filter(
            academic_year=table.academic_year,
            section_id__in=table.entries.values("assignment__section_id"),
            started_on__lte=table.ends_on,
        )
        .filter(Q(ended_on__isnull=True) | Q(ended_on__gte=table.starts_on))
        .select_related("student")
    )
    suffix = f"{table.revision}:{action}:{substitution.pk if substitution else 0}"
    for placement in students:
        for user in family(placement.student):
            add(
                user,
                f"schedule:{table.pk}:{suffix}:{placement.student_id}",
                f"{table.title}: {action}",
                reverse("scheduling:overview"),
                category_name="scheduling",
                timetable=table,
                student=placement.student,
            )
    ids = set(table.entries.values_list("assignment__teacher__user_id", flat=True))
    if substitution:
        ids.add(substitution.teacher.user_id)
    for user in ids:
        add(
            user,
            f"schedule:{table.pk}:{suffix}:teacher",
            f"{table.title}: {action}",
            reverse("scheduling:overview"),
            category_name="scheduling",
            timetable=table,
        )


def publication_notice(row):
    if row.state not in ("published", "cancelled"):
        return
    # Selection is repeated on reads; this is delivery, never an access grant.
    for user in get_user_model().objects.filter(is_active=True):
        add(
            user.pk,
            f"publication:{row.pk}:{row.revision}",
            f"{row.title}: {row.state}",
            reverse("communications:publication", args=[row.pk]),
            category_name="communications",
            publication=row,
            available_at=row.publish_at,
        )


def message_notice(message):
    row = message.conversation
    user = row.recipient_id if row.initiator_id == message.sender_id else row.initiator_id
    add(
        user,
        f"message:{message.pk}",
        f"New message: {row.subject}",
        reverse("communications:thread", args=[row.pk]),
        category_name="communications",
        conversation=row,
        student=row.student,
    )


def visible(user):
    from django.db.models import CharField, Exists, OuterRef, Value
    from django.db.models.functions import Cast, Concat

    from learning.models import Submission

    if not Notice.objects.filter(recipient=user).exists():
        return Notice.objects.none()
    from learning.selectors import visible as assignments
    from scheduling.access import children
    from scheduling.selectors import tables

    from .selectors import conversations, publications

    completed = Submission.objects.filter(
        assignment_id=OuterRef("assignment_id"),
        student_id=OuterRef("student_id"),
        state__in=["submitted", "reviewed", "graded", "excused"],
    )
    current_due_key = Concat(
        Value("due:"),
        Cast("assignment_id", CharField()),
        Value(":"),
        Cast("assignment__revision", CharField()),
        Value(":"),
        Cast("student_id", CharField()),
    )
    personal = (
        Q(student__isnull=True)
        | Q(student__in=children(user))
        | Q(conversation__in=conversations(user))
    )

    return (
        Notice.objects.alias(work_complete=Exists(completed))
        .filter(
            ~Q(key__startswith="due:")
            | Q(key=current_due_key, work_complete=False, assignment__due_at__gte=timezone.now()),
        )
        .filter(personal, recipient=user, available_at__lte=timezone.now())
        .filter(
            Q(publication__in=publications(user))
            | Q(assignment__in=assignments(user))
            | Q(timetable__in=tables(user))
            | Q(conversation__in=conversations(user))
        )
        .select_related("student")
    )
