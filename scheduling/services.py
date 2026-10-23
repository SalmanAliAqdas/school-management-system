from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models import Q

from attendance.calendar import SchoolCalendar, school_now
from attendance.models import LeaveRequest
from audit.services import record_event

from .access import require
from .models import (
    Availability,
    Booking,
    Entry,
    Period,
    Room,
    ScheduleHistory,
    Substitution,
    Timetable,
    WorkloadLimit,
)


def lock():
    # A school-wide transaction lock also serializes schedules in overlapping years.
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(715001)")


def dates(table, period):
    start = table.starts_on + timedelta(days=(period.weekday - table.starts_on.weekday()) % 7)
    calendar = SchoolCalendar(table.academic_year)
    return [
        start + timedelta(days=n)
        for n in range(0, (table.ends_on - start).days + 1, 7)
        if not calendar.reason(start + timedelta(days=n))
        or not calendar.policy(start + timedelta(days=n))
    ]


def validate_table(table):
    table.full_clean()
    year = table.academic_year
    if (
        year.status != "open"
        or not year.starts_on <= table.starts_on <= table.ends_on <= year.ends_on
    ):
        raise ValidationError("Use dates within an open academic year.")
    if table.term_id and (
        table.term.academic_year_id != year.pk
        or not table.term.starts_on <= table.starts_on <= table.ends_on <= table.term.ends_on
    ):
        raise ValidationError("Version dates must fall within its selected term.")


def validate_entry(entry):
    table, period, assigned = entry.timetable, entry.period, entry.assignment
    validate_table(table)
    if not assigned.is_active:
        raise ValidationError("This teaching assignment has been revoked.")
    if (
        period.academic_year_id != table.academic_year_id
        or assigned.academic_year_id != table.academic_year_id
        or period.kind != "lesson"
    ):
        raise ValidationError(
            "Choose a teaching period and assignment from the same academic year."
        )
    if not entry.room.is_active:
        raise ValidationError("This room is unavailable.")
    teacher = assigned.teacher
    days = dates(table, period)
    if not days:
        raise ValidationError("No teaching dates remain after weekdays and school closures.")
    if (
        not teacher.is_active
        or teacher.joined_on > min(days)
        or (teacher.left_on and teacher.left_on < max(days))
    ):
        raise ValidationError("Teacher employment must cover every scheduled lesson.")
    if Availability.objects.filter(
        teacher=teacher,
        kind="unavailable",
        period__weekday=period.weekday,
        period__academic_year=table.academic_year,
        period__starts_at__lt=period.ends_at,
        period__ends_at__gt=period.starts_at,
    ).exists():
        raise ValidationError("Teacher is unavailable during this period.")
    leaves = LeaveRequest.objects.filter(
        teacher=teacher, state="approved", starts_on__lte=max(days), ends_on__gte=min(days)
    )
    if any(leave.starts_on <= day <= leave.ends_on for leave in leaves for day in days):
        raise ValidationError(
            "Approved leave overlaps these lessons; shorten the version or resolve leave first."
        )
    if (
        Period.objects.filter(
            academic_year=table.academic_year,
            shift=period.shift,
            weekday=period.weekday,
            starts_at__lt=period.ends_at,
            ends_at__gt=period.starts_at,
        )
        .exclude(kind="lesson")
        .exists()
    ):
        raise ValidationError("The lesson overlaps a break, lunch or assembly.")
    peers = (
        Entry.objects.filter(
            Q(timetable=table) | Q(timetable__state="published"),
            timetable__starts_on__lte=table.ends_on,
            timetable__ends_on__gte=table.starts_on,
            period__weekday=period.weekday,
            period__starts_at__lt=period.ends_at,
            period__ends_at__gt=period.starts_at,
        )
        .exclude(pk=entry.pk)
        .select_related("timetable__academic_year", "period", "assignment")
    )
    for peer in peers:
        if not set(days).intersection(dates(peer.timetable, peer.period)):
            continue
        if peer.assignment.teacher_id == assigned.teacher_id:
            raise ValidationError("Teacher conflict: another class occupies this time.")
        if peer.assignment.section_id == assigned.section_id:
            raise ValidationError("Section/cohort conflict: another subject occupies this time.")
        if peer.room_id == entry.room_id:
            raise ValidationError("Room or laboratory conflict: this space is occupied.")


def history(actor, table, action, detail=None):
    ScheduleHistory.objects.create(actor=actor, timetable=table, action=action, detail=detail or {})
    record_event("scheduling." + action, actor=actor, target=table.pk)


@transaction.atomic
def save_table(actor, table):
    require(actor, "scheduling.manage_timetable")
    lock()
    if table.pk and Timetable.objects.get(pk=table.pk).state != "draft":
        raise ValidationError("Published versions are immutable; copy to a new draft.")
    table.state = "draft"
    validate_table(table)
    table.save()
    history(actor, table, "draft_saved")
    return table


@transaction.atomic
def save_entry(actor, entry, revision):
    require(actor, "scheduling.manage_timetable")
    lock()
    table = Timetable.objects.get(pk=entry.timetable_id)
    if table.state != "draft" or table.revision != revision:
        raise ValidationError("This draft changed or was published. Reload before editing.")
    entry.timetable = table
    validate_entry(entry)
    entry.full_clean()
    entry.save()
    table.revision += 1
    table.save(update_fields=["revision", "updated_at"])
    history(actor, table, "entry_saved", {"entry": entry.pk})
    return entry


@transaction.atomic
def transition(actor, pk, action):
    require(actor, "scheduling.manage_timetable")
    lock()
    table = Timetable.objects.get(pk=pk)
    if action == "publish" and table.state == "draft":
        entries = list(table.entries.select_related("period", "assignment__teacher", "room"))
        if not entries:
            raise ValidationError("Add lessons before publication.")
        for entry in entries:
            validate_entry(entry)
        zone = school_now().tzinfo
        Booking.objects.bulk_create(
            [
                Booking(
                    entry=entry,
                    date=day,
                    starts_at=datetime.combine(day, entry.period.starts_at, tzinfo=zone),
                    ends_at=datetime.combine(day, entry.period.ends_at, tzinfo=zone),
                    teacher=entry.assignment.teacher,
                    section=entry.assignment.section,
                    room=entry.room,
                )
                for entry in entries
                for day in dates(table, entry.period)
            ]
        )
        table.state = "published"
    elif action == "archive" and table.state == "published":
        table.state = "archived"
        Booking.objects.filter(entry__timetable=table).update(active=False)
    else:
        raise ValidationError("Invalid timetable transition.")
    table.save()
    history(actor, table, action)
    from communications.notices import schedule_notice

    schedule_notice(table, action)
    return table


@transaction.atomic
def copy_table(actor, pk):
    require(actor, "scheduling.manage_timetable")
    lock()
    original = Timetable.objects.get(pk=pk)
    copied = Timetable.objects.create(
        title=original.title + " (copy)",
        academic_year=original.academic_year,
        term=original.term,
        starts_on=original.starts_on,
        ends_on=original.ends_on,
    )
    Entry.objects.bulk_create(
        [
            Entry(timetable=copied, period=e.period, assignment=e.assignment, room=e.room)
            for e in original.entries.all()
        ]
    )
    history(actor, copied, "copied", {"source": pk})
    return copied


@transaction.atomic
def save_setup(actor, instance):
    require(actor, "scheduling.manage_timetable")
    lock()
    if (
        instance.pk
        and isinstance(instance, Period)
        and Entry.objects.filter(period=instance).exists()
    ):
        raise ValidationError("Used periods are protected. Create a new period.")
    instance.full_clean()
    instance.save()
    record_event(
        "scheduling.setup", actor=actor, target=f"{instance._meta.model_name}:{instance.pk}"
    )
    return instance


@transaction.atomic
def substitute(actor, entry_id, day, teacher, reason, approve=False):
    require(actor, "scheduling.manage_timetable")
    lock()
    entry = Entry.objects.select_related("timetable__academic_year", "period", "assignment").get(
        pk=entry_id
    )
    if entry.timetable.state != "published" or day not in dates(entry.timetable, entry.period):
        raise ValidationError("Choose a published lesson on a teaching date.")
    if (
        teacher.pk == entry.assignment.teacher_id
        or not teacher.is_active
        or teacher.joined_on > day
        or (teacher.left_on and teacher.left_on < day)
    ):
        raise ValidationError("Choose a different, currently employed teacher.")
    from academics.models import TeachingAssignment

    if not TeachingAssignment.objects.filter(
        teacher=teacher,
        academic_year=entry.timetable.academic_year,
        subject=entry.assignment.subject,
    ).exists():
        raise ValidationError("Substitute needs an authorized subject assignment in this year.")
    if (
        LeaveRequest.objects.filter(
            teacher=teacher, state="approved", starts_on__lte=day, ends_on__gte=day
        ).exists()
        or Availability.objects.filter(
            teacher=teacher, period=entry.period, kind="unavailable"
        ).exists()
    ):
        raise ValidationError("Substitute is unavailable or on approved leave.")
    peers = Entry.objects.filter(
        timetable__state="published",
        timetable__starts_on__lte=day,
        timetable__ends_on__gte=day,
        period__weekday=day.weekday(),
        period__starts_at__lt=entry.period.ends_at,
        period__ends_at__gt=entry.period.starts_at,
        assignment__teacher=teacher,
    )
    duties = Substitution.objects.filter(
        date=day,
        state="approved",
        teacher=teacher,
        entry__period__starts_at__lt=entry.period.ends_at,
        entry__period__ends_at__gt=entry.period.starts_at,
    )
    if peers.exists() or duties.exists():
        raise ValidationError("Substitute already has a lesson or substitution at this time.")
    row = Substitution.objects.filter(
        entry=entry, date=day, state="pending"
    ).first() or Substitution(entry=entry, date=day)
    row.teacher, row.reason, row.state = teacher, reason, "approved" if approve else "pending"
    row.full_clean()
    row.save()
    history(actor, entry.timetable, "substitution", {"substitution": row.pk, "state": row.state})
    if approve:
        Booking.objects.filter(entry=entry, date=day, active=True).update(teacher=teacher)
        from communications.notices import schedule_notice

        schedule_notice(entry.timetable, "substitution", row)
    return row


def assistance(table):
    entries = list(
        table.entries.select_related(
            "assignment__teacher", "assignment__section__school_class", "period", "room"
        )
    )
    workload = {}
    for entry in entries:
        item = workload.setdefault(
            entry.assignment.teacher_id,
            {"teacher": entry.assignment.teacher, "periods": 0, "daily": {}},
        )
        item["periods"] += 1
        day = entry.period.get_weekday_display()
        item["daily"][day] = item["daily"].get(day, 0) + 1
    limits = {x.teacher_id: x for x in WorkloadLimit.objects.all()}
    for key, item in workload.items():
        limit = limits.get(key)
        item["warning"] = bool(
            limit and (item["periods"] > limit.weekly or max(item["daily"].values()) > limit.daily)
        )
    periods = Period.objects.filter(academic_year=table.academic_year, kind="lesson")
    sections = {e.assignment.section_id for e in entries}
    total = periods.count() * len(sections)
    allocated = {(e.assignment.section_id, e.period_id) for e in entries}
    section_map = {e.assignment.section_id: e.assignment.section for e in entries}
    missing = [
        {"section": section, "period": period}
        for key, section in section_map.items()
        for period in periods
        if (key, period.pk) not in allocated
    ]
    return {
        "missing_slots": missing[:100],
        "workload": list(workload.values()),
        "assigned": len(entries),
        "capacity": total,
        "unassigned": max(0, total - len(entries)),
        "rooms": Room.objects.filter(is_active=True),
    }


@transaction.atomic
def remove_entry(actor, pk, revision):
    require(actor, "scheduling.manage_timetable")
    lock()
    entry = Entry.objects.select_related("timetable").get(pk=pk)
    table = entry.timetable
    if table.state != "draft" or table.revision != revision:
        raise ValidationError("Reload this draft before removing a lesson.")
    history(actor, table, "entry_removed", {"entry": entry.pk})
    entry.delete()
    table.revision += 1
    table.save()


@transaction.atomic
def cancel_substitution(actor, pk, reason):
    require(actor, "scheduling.manage_timetable")
    lock()
    row = Substitution.objects.select_related("entry__timetable", "entry__assignment").get(pk=pk)
    if not reason.strip() or row.state == "cancelled":
        raise ValidationError("Provide a reason for an active substitution.")
    Booking.objects.filter(entry=row.entry, date=row.date, active=True).update(
        teacher=row.entry.assignment.teacher
    )
    row.state = "cancelled"
    row.save()
    history(
        actor, row.entry.timetable, "substitution_cancelled", {"substitution": pk, "reason": reason}
    )


def suggestions(table, period):
    from academics.models import TeachingAssignment

    available_rooms = []
    available_teachers = []
    errors = set()
    for assignment in TeachingAssignment.objects.filter(
        academic_year=table.academic_year
    ).select_related("teacher"):
        for room in Room.objects.filter(is_active=True):
            try:
                validate_entry(
                    Entry(timetable=table, period=period, assignment=assignment, room=room)
                )
            except ValidationError as exc:
                errors.update(exc.messages)
            else:
                available_rooms.append(room)
                available_teachers.append(assignment)
    return {
        "rooms": {r.pk: r for r in available_rooms}.values(),
        "teachers": {a.pk: a for a in available_teachers}.values(),
        "conflicts": sorted(errors),
    }


@transaction.atomic
def assignment_access(actor, pk, active, reason):
    from academics.models import TeachingAssignment

    require(actor, "academics.change_teachingassignment")
    lock()
    row = TeachingAssignment.all_objects.select_for_update().get(pk=pk)
    if not reason.strip():
        raise ValidationError("A reason is required for an assignment access decision.")
    from .models import AssignmentAccessEvent

    event = AssignmentAccessEvent(assignment=row, actor=actor, active=active, reason=reason)
    event.full_clean()
    event.save()
    row.is_active = active
    row.save(update_fields=["is_active", "updated_at"])
    from audit.services import record_event

    record_event(
        "academic.assignment_enabled" if active else "academic.assignment_revoked",
        actor=actor,
        target=row.pk,
    )
    # History keeps the reason alongside every affected timetable without editing lessons.
    for table in Timetable.objects.filter(entries__assignment=row).distinct():
        history(
            actor,
            table,
            "assignment_access",
            {"assignment": pk, "active": active, "reason": reason},
        )
    return row
