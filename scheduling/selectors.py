from django.db.models import Q

from .access import current_assignments, placements
from .models import Entry, Substitution, Timetable


def tables(user, personal_role=None):
    rows = Timetable.objects.all()
    if not personal_role and user.has_perm("scheduling.manage_timetable"):
        return rows
    scope = Q(entries__assignment__in=current_assignments(user)) | Q(
        entries__substitutions__teacher__user=user, entries__substitutions__state="approved"
    )
    if personal_role:
        scope = Q(pk__in=[])
    for p in placements(user, role=personal_role):
        scope |= Q(
            academic_year_id=p.academic_year_id, entries__assignment__section_id=p.section_id
        )
    return rows.filter(scope, state="published").distinct()


def lessons(user, day=None, child=None, personal_role=None):
    rows = Entry.objects.filter(timetable__in=tables(user, personal_role)).select_related(
        "timetable__academic_year",
        "period",
        "assignment__teacher",
        "assignment__section__school_class",
        "assignment__subject",
        "room",
    )
    if child or personal_role or not user.has_perm("scheduling.manage_timetable"):
        scope = Q(assignment__in=current_assignments(user)) | Q(
            substitutions__teacher__user=user, substitutions__state="approved"
        )
        if child or personal_role:
            scope = Q(pk__in=[])
        for p in placements(user, day, role=personal_role):
            if child is None or p.student_id == child.pk:
                scope |= Q(
                    timetable__academic_year_id=p.academic_year_id,
                    assignment__section_id=p.section_id,
                )
        rows = rows.filter(scope)
    if day:
        rows = rows.filter(
            timetable__starts_on__lte=day,
            timetable__ends_on__gte=day,
            period__weekday=day.weekday(),
            timetable__state="published",
        )
    return rows.distinct().order_by(
        "period__weekday", "period__starts_at", "assignment__section_id"
    )


def daily(user, day, child=None, personal_role=None):
    from .services import dates

    result = []
    for row in lessons(user, day, child, personal_role):
        if day not in dates(row.timetable, row.period):
            continue
        row.substitute = (
            Substitution.objects.filter(entry=row, date=day, state="approved")
            .select_related("teacher")
            .first()
        )
        result.append(row)
    return result
