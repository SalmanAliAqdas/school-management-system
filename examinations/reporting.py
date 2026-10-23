from collections import Counter, defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import OuterRef, Subquery

from .models import ExaminationSettings, PublishedResult, ResultPublication
from .selectors import can_oversee, candidates_visible_to, sessions_visible_to, subjects_visible_to

MAX_RESULTS = 5000


def current_results(user, *, session=None):
    latest = (
        ResultPublication.objects.filter(session_id=OuterRef("publication__session_id"))
        .order_by("-version")
        .values("pk")[:1]
    )
    rows = PublishedResult.objects.filter(
        publication_id=Subquery(latest), candidate__in=candidates_visible_to(user)
    ).select_related(
        "publication__session", "candidate__student", "candidate__cohort__section__school_class"
    )
    return rows.filter(publication__session=session) if session else rows


def published_subject_history(user, assignment, student):
    """Project approved snapshots to one assigned subject, without full report data."""
    from .selectors import authorized_subjects

    if assignment.teacher.user_id != user.pk:
        return []
    allowed = authorized_subjects(user).filter(
        cohort__session__academic_year=assignment.academic_year,
        cohort__section=assignment.section,
        subject=assignment.subject,
    )
    latest = (
        ResultPublication.objects.filter(session_id=OuterRef("publication__session_id"))
        .order_by("-version")
        .values("pk")[:1]
    )
    rows = (
        PublishedResult.objects.filter(
            publication_id=Subquery(latest),
            candidate__student=student,
            candidate__cohort__subjects__in=allowed,
            candidate__withheld=False,
            publication__session__state__in=["published", "archived"],
            candidate__session__ends_on__gte=assignment.teacher.joined_on,
        )
        .exclude(data__outcome="withheld")
        .select_related("publication__session")
    )
    if assignment.teacher.left_on:
        rows = rows.filter(candidate__session__starts_on__lte=assignment.teacher.left_on)
    history = []
    for row in rows.order_by("publication__session__ends_on", "pk").distinct()[:100]:
        subjects = [
            subject
            for subject in row.data.get("subjects", [])
            if subject["subject_id"] == assignment.subject_id
        ]
        if subjects:
            history.append(
                {
                    "session": row.publication.session.name,
                    "version": row.publication.version,
                    "subjects": subjects,
                }
            )
    return history


def analytics(user, session):
    """Subject teachers receive only assigned-subject metrics, never full report data."""
    if session not in sessions_visible_to(user):
        raise ValidationError("Choose an examination visible to your account.")
    latest = session.publications.first()
    if not latest:
        return {
            "total": 0,
            "complete": 0,
            "incomplete": 0,
            "average": None,
            "pass_percentage": None,
            "grades": [],
            "subjects": [],
            "sections": [],
            "support": [],
        }
    rows = latest.results.select_related(
        "candidate__cohort__section__school_class", "candidate__student"
    )
    if rows.count() > MAX_RESULTS:
        raise ValidationError("Choose an examination with at most 5,000 candidates for analytics.")
    oversight = can_oversee(user, session)
    settings = ExaminationSettings.objects.first() or ExaminationSettings()
    allowed = {(s.cohort_id, s.subject_id) for s in subjects_visible_to(user, session)}
    subject_groups = defaultdict(list)
    section_groups = defaultdict(list)
    complete, incomplete, grades, support = [], 0, Counter(), []
    for row in rows:
        data = row.data
        if data["outcome"] == "withheld":
            continue
        for subject in data["subjects"]:
            if oversight or (row.candidate.cohort_id, subject["subject_id"]) in allowed:
                if subject["raw_percentage"] is not None and subject["outcome"] in ("pass", "fail"):
                    subject_groups[subject["subject"]].append(subject)
        if not oversight:
            continue
        if data["outcome"] in ("pass", "fail") and data["raw_percentage"] is not None:
            complete.append(data)
            grades[data["grade"]] += 1
            section_groups[f"{data['class']} · {data['section']}"].append(data)
            if (
                data["outcome"] == "fail"
                or Decimal(data["raw_percentage"]) < settings.support_threshold
            ):
                support.append(
                    {
                        "candidate": row.candidate,
                        "percentage": data["percentage"],
                        "reason": "Passing criteria not met"
                        if data["outcome"] == "fail"
                        else "Below configured academic support threshold",
                    }
                )
        else:
            incomplete += 1
            support.append(
                {
                    "candidate": row.candidate,
                    "percentage": None,
                    "reason": "Incomplete assessment; academic review",
                }
            )

    def metrics(values):
        marks = [Decimal(v["raw_percentage"]) for v in values]
        return {
            "count": len(values),
            "average": str((sum(marks) / len(marks)).quantize(Decimal(".01"))) if marks else None,
            "highest": str(max(marks).quantize(Decimal(".01"))) if marks else None,
            "lowest": str(min(marks).quantize(Decimal(".01"))) if marks else None,
            "pass_percentage": str(
                (Decimal(sum(v["outcome"] == "pass" for v in values)) / len(values) * 100).quantize(
                    Decimal(".01")
                )
            )
            if values
            else None,
        }

    return {
        "total": len(complete) + incomplete,
        "complete": len(complete),
        "incomplete": incomplete,
        **metrics(complete),
        "grades": [{"label": label, "count": count} for label, count in grades.items()],
        "subjects": [
            {"label": name, **metrics(values)} for name, values in sorted(subject_groups.items())
        ],
        "sections": [
            {"label": name, **metrics(values)} for name, values in sorted(section_groups.items())
        ],
        "support": support,
        "oversight": oversight,
    }
