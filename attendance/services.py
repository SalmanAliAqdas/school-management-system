from datetime import time

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.db.models import F
from django.utils import timezone

from academics.models import AcademicYear
from academics.services import teacher_year_writable
from audit.services import record_event
from core.operations import require_capability
from people.models import GuardianStudent

from .calendar import SchoolCalendar, policy_on, school_now
from .models import (
    AbsenceNotification,
    AttendanceCorrection,
    CalendarEvent,
    LeaveRequest,
    StaffAttendance,
    StaffRegister,
    StaffStatus,
    StudentAttendance,
    StudentRegister,
    StudentStatus,
)
from .selectors import (
    enrollment_roster,
    sections_markable_by,
    staff_entries_visible_to,
    staff_roster,
    student_entries_visible_to,
)


def lock_year(pk, *, open_only=True):
    year = AcademicYear.objects.select_for_update().get(pk=pk)
    if open_only and year.status != "open":
        raise ValidationError("This academic year is closed or archived.")
    return year


def checked_values(raw, policy, *, staff=False):
    statuses = StaffStatus.values if staff else StudentStatus.values
    status = raw.get("status", "")
    arrival = raw.get("arrival_time") or None
    notes = str(raw.get("notes", "")).strip()
    if isinstance(arrival, str):
        try:
            arrival = time.fromisoformat(arrival)
        except ValueError as exc:
            raise ValidationError("Enter a valid arrival time.") from exc
    if status not in ["", *statuses] or len(notes) > 500:
        raise ValidationError(
            "Choose a valid attendance status and a note of at most 500 characters."
        )
    if arrival and (not isinstance(arrival, time) or arrival.tzinfo):
        raise ValidationError("Arrival must be a local school time without a timezone offset.")
    if arrival and status not in {"present", "late"}:
        raise ValidationError("Arrival time applies only to present or late attendance.")
    if arrival:
        status = "late" if arrival > policy.late_after else "present"
    if status == "excused" and not notes:
        raise ValidationError("Explain the excused absence in the note.")
    return {"status": status, "arrival_time": arrival, "notes": notes}


def check_submission(actor, day, policy, final, reason, *, staff=False):
    now = school_now()
    if day > now.date():
        raise ValidationError("Attendance cannot be recorded for a future school date.")
    after_cutoff = day < now.date() or now.time().replace(tzinfo=None) > policy.cutoff_time
    if final and after_cutoff:
        permission = (
            "attendance.manage_staff_attendance" if staff else "attendance.view_all_attendance"
        )
        if not actor.has_perm(permission) or not reason.strip():
            raise ValidationError(
                "The submission cutoff has passed. An authorized administrator must submit "
                "with a late-submission reason."
            )


@transaction.atomic
def save_student_register(
    actor, *, year_id, section_id, day, rows, expected_version=0, final=False, reason=""
):
    require_capability(actor, "attendance.mark_attendance")
    year = lock_year(year_id)
    section = sections_markable_by(actor, year).filter(pk=section_id).first()
    if not section:
        raise PermissionDenied
    if not actor.has_perm("attendance.view_all_attendance") and not teacher_year_writable(
        actor, year, day=day
    ):
        raise PermissionDenied
    calendar = SchoolCalendar(year)
    if calendar.reason(day):
        raise ValidationError(calendar.reason(day))
    register = (
        StudentRegister.objects.select_for_update()
        .filter(academic_year=year, section=section, attendance_on=day)
        .first()
    )
    if register and (register.state == "final" or register.version != expected_version):
        raise ValidationError(
            "This register was finalized or changed by another user. Reload before continuing."
        )
    if not register and expected_version:
        raise ValidationError("This register has changed. Reload the page.")
    policy = register.policy if register else policy_on(year, day)
    check_submission(actor, day, policy, final, reason)
    roster = list(enrollment_roster(year, section, day))
    eligible = {str(enrollment.pk): enrollment for enrollment in roster}
    if not eligible:
        raise ValidationError("No students have a valid enrollment in this section on this date.")
    if set(rows) != set(eligible):
        raise ValidationError(
            "The submitted roster does not match valid enrollments. Reload the register."
        )
    values = {key: checked_values(value, policy) for key, value in rows.items()}
    if final and any(not value["status"] for value in values.values()):
        raise ValidationError(
            "The register is incomplete. Mark every student before final submission."
        )
    if not register:
        register = StudentRegister.objects.create(
            academic_year=year,
            section=section,
            attendance_on=day,
            policy=policy,
            created_by=actor,
            updated_by=actor,
        )
    existing = {str(entry.enrollment_id): entry for entry in register.entries.select_for_update()}
    register.entries.filter(
        pk__in=[existing[key].pk for key in set(existing) - set(eligible)]
    ).delete()
    new_entries, updated_entries = [], []
    for key, enrollment in eligible.items():
        entry = existing.get(key) or StudentAttendance(
            register=register, enrollment=enrollment, student=enrollment.student, attendance_on=day
        )
        for name, value in values[key].items():
            setattr(entry, name, value)
        entry.recorded_by = actor
        entry.updated_at = timezone.now()
        (updated_entries if entry.pk else new_entries).append(entry)
    StudentAttendance.objects.bulk_create(new_entries)
    StudentAttendance.objects.bulk_update(
        updated_entries, ["status", "arrival_time", "notes", "recorded_by", "updated_at"]
    )
    register.version += 1
    register.updated_by = actor
    if final:
        register.state, register.submitted_at, register.submitted_by = (
            "final",
            timezone.now(),
            actor,
        )
        register.submission_reason = reason.strip()
    register.full_clean()
    register.save()
    if final:
        sync_notifications(
            list(register.entries.select_related("register").filter(status="absent"))
        )
    record_event(
        "attendance.student_submitted" if final else "attendance.student_draft_saved",
        actor=actor,
        target=register.pk,
    )
    return register


def person_filter(person):
    return {"teacher": person} if person._meta.model_name == "teacher" else {"staff": person}


def approved_leave(person, day):
    return LeaveRequest.objects.filter(
        **person_filter(person), state="approved", starts_on__lte=day, ends_on__gte=day
    ).exists()


def approved_leave_keys(day):
    return {
        f"teacher:{teacher}" if teacher else f"staff:{staff}"
        for teacher, staff in LeaveRequest.objects.filter(
            state="approved", starts_on__lte=day, ends_on__gte=day
        ).values_list("teacher_id", "staff_id")
    }


def check_staff_value(person, day, value, calendar, leave_keys=None):
    if calendar.is_closure(day):
        if value["status"] != "closure":
            raise ValidationError(
                "A school closure must be recorded with School closure status for every employee."
            )
    elif value["status"] == "closure":
        raise ValidationError(
            "School closure status requires an authorized closure on the school calendar."
        )
    elif (
        f"{person._meta.model_name}:{person.pk}" in leave_keys
        if leave_keys is not None
        else approved_leave(person, day)
    ):
        if value["status"] != "leave":
            raise ValidationError("This employee has approved leave; select Approved leave.")
    elif value["status"] == "leave":
        raise ValidationError(
            "Approved leave status requires an approved leave request for this date."
        )


@transaction.atomic
def save_staff_register(actor, *, year_id, day, rows, expected_version=0, final=False, reason=""):
    require_capability(actor, "attendance.manage_staff_attendance")
    year = lock_year(year_id)
    calendar = SchoolCalendar(year)
    if calendar.reason(day, staff=True) and not calendar.is_closure(day):
        raise ValidationError(calendar.reason(day, staff=True))
    register = (
        StaffRegister.objects.select_for_update()
        .filter(academic_year=year, attendance_on=day)
        .first()
    )
    if register and (register.state == "final" or register.version != expected_version):
        raise ValidationError(
            "This staff register was finalized or changed. Reload before continuing."
        )
    if not register and expected_version:
        raise ValidationError("Reload this staff register before saving.")
    policy = register.policy if register else policy_on(year, day)
    check_submission(actor, day, policy, final, reason, staff=True)
    roster = dict(staff_roster(day))
    if not roster or set(rows) != set(roster):
        raise ValidationError(
            "The submitted roster must match all eligible employees. Reload the register."
        )
    values = {key: checked_values(value, policy, staff=True) for key, value in rows.items()}
    leave_keys = approved_leave_keys(day)
    for key, value in values.items():
        if value["status"]:
            check_staff_value(roster[key], day, value, calendar, leave_keys)
    if final and any(not value["status"] for value in values.values()):
        raise ValidationError(
            "The staff register is incomplete. Mark every employee before submission."
        )
    if not register:
        register = StaffRegister.objects.create(
            academic_year=year, attendance_on=day, policy=policy, created_by=actor, updated_by=actor
        )
    existing = {entry.person_key: entry for entry in register.entries.select_for_update()}
    register.entries.filter(
        pk__in=[existing[key].pk for key in set(existing) - set(roster)]
    ).delete()
    new_entries, updated_entries = [], []
    for key, person in roster.items():
        entry = existing.get(key) or StaffAttendance(
            register=register, attendance_on=day, **person_filter(person)
        )
        for name, value in values[key].items():
            setattr(entry, name, value)
        entry.recorded_by = actor
        entry.updated_at = timezone.now()
        (updated_entries if entry.pk else new_entries).append(entry)
    StaffAttendance.objects.bulk_create(new_entries)
    StaffAttendance.objects.bulk_update(
        updated_entries, ["status", "arrival_time", "notes", "recorded_by", "updated_at"]
    )
    register.version += 1
    register.updated_by = actor
    if final:
        register.state, register.submitted_at, register.submitted_by = (
            "final",
            timezone.now(),
            actor,
        )
        register.submission_reason = reason.strip()
    register.full_clean()
    register.save()
    record_event(
        "attendance.staff_submitted" if final else "attendance.staff_draft_saved",
        actor=actor,
        target=register.pk,
    )
    return register


def snapshot(entry):
    return {
        "status": entry.status,
        "arrival_time": entry.arrival_time.isoformat() if entry.arrival_time else None,
        "notes": entry.notes,
    }


def correction_window(actor, entry):
    age = (school_now().date() - entry.attendance_on).days
    if (
        age > entry.register.policy.correction_window_days
        or entry.register.academic_year.status == "archived"
    ) and not actor.has_perm("attendance.override_correction_window"):
        raise ValidationError("This attendance record is outside the authorized correction window.")


@transaction.atomic
def sync_notifications(entries):
    entries = entries if isinstance(entries, list) else [entries]
    if not entries:
        return
    AbsenceNotification.objects.filter(
        entry_id__in=[entry.pk for entry in entries],
        state="active",
        revision__lt=F("entry__revision"),
    ).update(state="superseded", superseded_at=timezone.now())
    absent = {
        entry.student_id: entry
        for entry in entries
        if entry.register.state == "final" and entry.status == "absent"
    }
    users = get_user_model().objects
    backend = "django.contrib.auth.backends.ModelBackend"
    permitted = (
        users.with_perm("accounts.access_parent_dashboard", backend=backend)
        .filter(pk__in=users.with_perm("attendance.view_attendance", backend=backend))
        .filter(pk__in=users.with_perm("people.view_student", backend=backend))
    )
    links = (
        GuardianStudent.objects.filter(student_id__in=absent, guardian__user__in=permitted)
        .select_related("guardian")
        .select_for_update(of=("self",))
    )
    AbsenceNotification.objects.bulk_create(
        [
            AbsenceNotification(
                entry=absent[link.student_id],
                guardian=link.guardian,
                recipient_id=link.guardian.user_id,
                revision=absent[link.student_id].revision,
            )
            for link in links
        ],
        ignore_conflicts=True,
    )


@transaction.atomic
def request_correction(actor, *, kind, entry_id, values, reason):
    is_staff = kind == "staff"
    permission = (
        "attendance.request_staff_correction" if is_staff else "attendance.request_correction"
    )
    require_capability(actor, permission)
    source = staff_entries_visible_to(actor) if is_staff else student_entries_visible_to(actor)
    entry = source.filter(pk=entry_id).first()
    if not entry:
        raise PermissionDenied
    year = lock_year(entry.register.academic_year_id, open_only=False)
    if (
        not is_staff
        and not sections_markable_by(actor, year).filter(pk=entry.register.section_id).exists()
    ):
        raise PermissionDenied
    if (
        is_staff
        and not actor.has_perm("attendance.manage_staff_attendance")
        and entry.person.user_id != actor.pk
    ):
        raise PermissionDenied
    type(entry.register).objects.select_for_update().get(pk=entry.register_id)
    entry = (
        type(entry)
        .objects.select_for_update(of=("self",))
        .select_related(
            "register__policy",
            "register__academic_year",
            *(["teacher", "staff"] if is_staff else []),
        )
        .get(pk=entry.pk)
    )
    if entry.register.state != "final":
        raise ValidationError(
            "Edit a draft in its register. Only finalized attendance needs a correction request."
        )
    correction_window(actor, entry)
    if not reason.strip() or len(reason.strip()) > 500:
        raise ValidationError("A correction reason of at most 500 characters is required.")
    after = checked_values(values, entry.register.policy, staff=is_staff)
    if not after["status"]:
        raise ValidationError("A finalized attendance status cannot be cleared.")
    if is_staff:
        check_staff_value(entry.person, entry.attendance_on, after, SchoolCalendar(year))
    serial_after = {
        **after,
        "arrival_time": after["arrival_time"].isoformat() if after["arrival_time"] else None,
    }
    if snapshot(entry) == serial_after:
        raise ValidationError("The proposed attendance is unchanged.")
    correction = AttendanceCorrection(
        **({"staff_entry": entry} if is_staff else {"student_entry": entry}),
        before=snapshot(entry),
        after=serial_after,
        reason=reason.strip(),
        requested_by=actor,
    )
    correction.full_clean()
    correction.save()
    record_event("attendance.correction_requested", actor=actor, target=correction.pk)
    return correction


def apply_correction(correction, actor):
    entry = correction.entry
    if snapshot(entry) != correction.before:
        raise ValidationError("The original attendance changed. Submit a fresh correction request.")
    for name, value in checked_values(
        correction.after, entry.register.policy, staff=bool(correction.staff_entry_id)
    ).items():
        setattr(entry, name, value)
    entry.revision += 1
    entry.recorded_by = actor
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('schoolos.correction_id', %s, true)", [str(correction.pk)]
        )
    entry.full_clean()
    entry.save()
    if correction.student_entry_id:
        sync_notifications(entry)


@transaction.atomic
def decide_correction(actor, pk, *, approve, reason=""):
    preview = AttendanceCorrection.objects.select_related(
        "student_entry__register", "staff_entry__register"
    ).get(pk=pk)
    require_capability(
        actor,
        "attendance.approve_staff_correction"
        if preview.staff_entry_id
        else "attendance.approve_correction",
    )
    if preview.staff_entry_id:
        require_capability(actor, "attendance.view_all_staff_attendance")
    else:
        require_capability(actor, "attendance.view_all_attendance", student_scope=True)
    year_id = preview.entry.register.academic_year_id
    lock_year(year_id, open_only=False)
    correction = (
        AttendanceCorrection.objects.select_for_update(of=("self",))
        .select_related(
            "student_entry__register__policy",
            "student_entry__register__academic_year",
            "staff_entry__register__policy",
            "staff_entry__register__academic_year",
            "staff_entry__teacher",
            "staff_entry__staff",
        )
        .get(pk=pk)
    )
    if correction.state != "pending" or correction.requested_by_id == actor.pk:
        raise ValidationError("A different authorized reviewer must decide a pending correction.")
    if not approve and not reason.strip():
        raise ValidationError("Explain why this correction is rejected.")
    correction_window(actor, correction.entry)
    if approve and correction.staff_entry_id:
        check_staff_value(
            correction.entry.person,
            correction.entry.attendance_on,
            checked_values(correction.after, correction.entry.register.policy, staff=True),
            SchoolCalendar(correction.entry.register.academic_year),
        )
    correction.state = "approved" if approve else "rejected"
    correction.reviewed_by, correction.reviewed_at, correction.decision_reason = (
        actor,
        timezone.now(),
        reason.strip(),
    )
    correction.full_clean()
    correction.save()
    if approve:
        apply_correction(correction, actor)
    record_event(
        "attendance.correction_approved" if approve else "attendance.correction_rejected",
        actor=actor,
        target=correction.pk,
    )
    return correction


@transaction.atomic
def save_policy(actor, form):
    require_capability(actor, "attendance.manage_policy")
    year = lock_year(form.cleaned_data["academic_year"].pk)
    obj = form.save(commit=False)
    if obj.pk:
        from .models import AttendancePolicy

        original = AttendancePolicy.objects.select_for_update().get(pk=obj.pk)
        if original.studentregister_set.exists() or original.staffregister_set.exists():
            raise ValidationError(
                "A policy used by a register is immutable. Add a later policy revision instead."
            )
    newest = max(
        [
            day
            for day in [
                StudentRegister.objects.filter(academic_year=year)
                .order_by("-attendance_on")
                .values_list("attendance_on", flat=True)
                .first(),
                StaffRegister.objects.filter(academic_year=year)
                .order_by("-attendance_on")
                .values_list("attendance_on", flat=True)
                .first(),
            ]
            if day
        ],
        default=None,
    )
    if newest and obj.effective_from <= newest:
        raise ValidationError("New policy revisions must start after all existing registers.")
    obj.full_clean()
    obj.save()
    record_event("attendance.policy_saved", actor=actor, target=obj.pk)
    return obj


@transaction.atomic
def save_calendar_event(actor, form):
    require_capability(actor, "attendance.manage_policy")
    lock_year(form.cleaned_data["academic_year"].pk)
    obj = form.save(commit=False)
    if obj.pk:
        raise ValidationError(
            "Calendar events are append-only. Create an explicit new calendar event."
        )
    obj.created_by = actor
    obj.full_clean()
    obj.save()
    record_event("attendance.calendar_created", actor=actor, target=obj.pk)
    return obj


@transaction.atomic
def cancel_calendar_event(actor, pk, reason):
    require_capability(actor, "attendance.manage_policy")
    preview = CalendarEvent.objects.get(pk=pk)
    lock_year(preview.academic_year_id)
    event = CalendarEvent.objects.select_for_update().get(pk=pk)
    if event.is_cancelled or not reason.strip() or len(reason) > 500:
        raise ValidationError("An active calendar event and a cancellation reason are required.")
    event.is_cancelled = True
    event.cancellation_reason, event.cancelled_by, event.cancelled_at = (
        reason.strip(),
        actor,
        timezone.now(),
    )
    event.save(
        update_fields=[
            "is_cancelled",
            "cancellation_reason",
            "cancelled_by",
            "cancelled_at",
            "updated_at",
        ]
    )
    record_event("attendance.calendar_cancelled", actor=actor, target=pk)
    return event


def validate_person_scope(actor, person):
    if not actor.has_perm("attendance.manage_staff_attendance") and person.user_id != actor.pk:
        raise PermissionDenied
    if (
        person._meta.model_name == "staff"
        and person.user_id
        and hasattr(person.user, "teacher_profile")
    ):
        raise ValidationError(
            "Use this employee's teacher profile to keep one staff attendance history."
        )


@transaction.atomic
def request_leave(actor, *, year_id, person, starts_on, ends_on, kind, reason):
    require_capability(actor, "attendance.request_leave")
    validate_person_scope(actor, person)
    year = lock_year(year_id)
    person = type(person).objects.select_for_update().get(pk=person.pk)
    if not year.starts_on <= starts_on <= ends_on <= year.ends_on:
        raise ValidationError("Leave dates must be ordered and inside the academic year.")
    if (
        starts_on < person.joined_on
        or (person.left_on and ends_on > person.left_on)
        or (not person.is_active and not person.left_on)
    ):
        raise ValidationError("Leave dates must fall within the employee's known employment dates.")
    if not reason.strip():
        raise ValidationError("Explain the reason for leave.")
    leave = LeaveRequest(
        academic_year=year,
        **person_filter(person),
        starts_on=starts_on,
        ends_on=ends_on,
        kind=kind,
        reason=reason.strip(),
        requested_by=actor,
    )
    leave.full_clean()
    leave.save()
    record_event("attendance.leave_requested", actor=actor, target=leave.pk)
    return leave


@transaction.atomic
def decide_leave(actor, pk, *, approve, reason=""):
    require_capability(actor, "attendance.approve_leave")
    require_capability(actor, "attendance.view_all_staff_attendance")
    preview = LeaveRequest.objects.get(pk=pk)
    lock_year(preview.academic_year_id)
    leave = (
        LeaveRequest.objects.select_for_update(of=("self",))
        .select_related("teacher", "staff")
        .get(pk=pk)
    )
    if leave.state != "pending" or leave.requested_by_id == actor.pk:
        raise ValidationError(
            "A different authorized reviewer must decide a pending leave request."
        )
    if not approve and not reason.strip():
        raise ValidationError("Explain why this leave request is rejected.")
    affected = (
        list(
            StaffAttendance.objects.select_for_update(of=("self",))
            .filter(
                **person_filter(leave.person), attendance_on__range=(leave.starts_on, leave.ends_on)
            )
            .exclude(status="closure")
            .select_related("register__policy", "register__academic_year")
        )
        if approve
        else []
    )
    for entry in affected:
        if entry.register.state == "final":
            correction_window(actor, entry)
            if entry.corrections.filter(state="pending").exists():
                raise ValidationError(
                    "Resolve pending attendance corrections for these dates before approving leave."
                )
    leave.state = "approved" if approve else "rejected"
    leave.reviewed_by, leave.reviewed_at, leave.decision_reason = (
        actor,
        timezone.now(),
        reason.strip(),
    )
    leave.full_clean()
    leave.save()
    for entry in affected:
        if entry.status == "leave":
            continue
        after = {"status": "leave", "arrival_time": None, "notes": f"Approved leave #{leave.pk}"}
        if entry.register.state == "final":
            correction = AttendanceCorrection(
                staff_entry=entry,
                before=snapshot(entry),
                after=after,
                reason=f"Leave approval #{leave.pk}: {leave.reason}"[:500],
                requested_by=leave.requested_by,
                state="approved",
                reviewed_by=actor,
                reviewed_at=timezone.now(),
                decision_reason="Approved leave applied to the recorded date.",
            )
            correction.full_clean()
            correction.save()
            apply_correction(correction, actor)
        else:
            entry.status, entry.arrival_time, entry.notes, entry.recorded_by = (
                "leave",
                None,
                after["notes"],
                actor,
            )
            entry.save()
            entry.register.version += 1
            entry.register.updated_by = actor
            entry.register.save(update_fields=["version", "updated_by", "updated_at"])
    record_event(
        "attendance.leave_approved" if approve else "attendance.leave_rejected",
        actor=actor,
        target=leave.pk,
    )
    return leave
