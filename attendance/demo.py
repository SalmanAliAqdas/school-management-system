"""Append repeatable fictional attendance without overwriting any existing register."""

from datetime import timedelta

from django.core.exceptions import ValidationError

from people.models import Staff, Teacher

from . import calendar as attendance_calendar
from .calendar import SchoolCalendar
from .models import (
    AttendanceCorrection,
    AttendancePolicy,
    CalendarEvent,
    LeaveRequest,
    StaffRegister,
    StudentAttendance,
    StudentRegister,
)
from .selectors import enrollment_roster, staff_roster
from .services import (
    approved_leave_keys,
    decide_correction,
    decide_leave,
    request_correction,
    request_leave,
    save_staff_register,
    save_student_register,
)


def seed_attendance_demo(accounts, year, students, sections):
    if year.status != "open":
        return
    actor, reviewer = accounts["demo.schooladmin"], accounts["demo.principal"]
    expected_names = [
        ("Noor", "Meadow"),
        ("Mika", "Willow"),
        ("Arin", "Cedar"),
        ("Lina", "Brook"),
        ("Remy", "Haven"),
        ("Sora", "Fern"),
    ]
    if len(students) != len(expected_names) or any(
        (student.first_name, student.last_name) != expected_names[index]
        or student.admission_number != f"DEMO-{index + 1:04}"
        for index, student in enumerate(students)
    ):
        raise ValidationError(
            "Attendance demo student identifiers collide with an existing record."
        )
    if not AttendancePolicy.objects.filter(academic_year=year).exists():
        AttendancePolicy.objects.create(academic_year=year, effective_from=year.starts_on)
    end = min(attendance_calendar.school_now().date(), year.ends_on)
    start = max(year.starts_on, end - timedelta(days=27))
    calendar = SchoolCalendar(year)
    dates = calendar.working_dates(start, end)
    if not dates:
        return
    for title, kind, index in [
        ("DEMO: fictional public holiday", "public", 2),
        ("DEMO: fictional school closure", "closure", 5),
    ]:
        if not CalendarEvent.objects.filter(academic_year=year, title=title).exists():
            candidates = dates[index:] + dates[:index]
            for day in candidates:
                if (
                    not StudentRegister.objects.filter(
                        academic_year=year, attendance_on=day
                    ).exists()
                    and not StaffRegister.objects.filter(
                        academic_year=year, attendance_on=day
                    ).exists()
                ):
                    CalendarEvent.objects.create(
                        academic_year=year,
                        title=title,
                        kind=kind,
                        starts_on=day,
                        ends_on=day,
                        reason="Fictional attendance demonstration",
                        created_by=actor,
                    )
                    break
    employee_specs = [
        (
            Teacher,
            "DEMO-ATT-T001",
            {"first_name": "Elian", "last_name": "Vale", "department": "Teaching"},
        ),
        (
            Staff,
            "DEMO-ATT-S001",
            {
                "first_name": "Tess",
                "last_name": "Glen",
                "department": "Office",
                "job_title": "Fictional office coordinator",
            },
        ),
    ]
    people = []
    for model, number, defaults in employee_specs:
        person, _ = model.objects.get_or_create(
            employee_number=number, defaults={**defaults, "joined_on": year.starts_on}
        )
        if (
            person.first_name != defaults["first_name"]
            or person.last_name != defaults["last_name"]
            or person.user_id
        ):
            raise ValidationError(
                "Attendance demo employee identifiers collide with an existing record."
            )
        people.append(person)
    calendar = SchoolCalendar(year)
    dates = calendar.working_dates(start, end)
    if len(dates) < 4:
        return
    future = min(year.ends_on, end + timedelta(days=5))
    leave_specs = [
        (people[1], dates[1], "approved", "DEMO: approved fictional sick leave"),
        (people[0], dates[3], "rejected", "DEMO: rejected fictional casual leave"),
        (people[0], future, "pending", "DEMO: pending fictional leave"),
    ]
    for person, day, state, reason in leave_specs:
        if not LeaveRequest.objects.filter(reason=reason, academic_year=year).exists():
            from .models import StaffAttendance
            from .services import person_filter

            if (
                state == "approved"
                and StaffAttendance.objects.filter(
                    **person_filter(person), attendance_on=day
                ).exists()
            ):
                continue
            leave = request_leave(
                actor,
                year_id=year.pk,
                person=person,
                starts_on=day,
                ends_on=day,
                kind="sick" if state == "approved" else "casual",
                reason=reason,
            )
            if state != "pending":
                decide_leave(
                    reviewer,
                    leave.pk,
                    approve=state == "approved",
                    reason="Fictional demonstration decision",
                )
    student_index = {student.pk: index for index, student in enumerate(students)}
    created_register_ids = []
    for index, day in enumerate(dates):
        for section_index, section in enumerate(sections):
            if StudentRegister.objects.filter(
                academic_year=year, section=section, attendance_on=day
            ).exists():
                continue
            # Preserve an entirely missing register and a visible draft as separate examples.
            if section_index == 2 and index == len(dates) - 2:
                continue
            draft = section_index == 2 and day == dates[-1]
            roster = list(enrollment_roster(year, section, day))
            if not roster or any(
                enrollment.student_id not in student_index for enrollment in roster
            ):
                continue
            rows = {}
            for enrollment in roster:
                number = student_index[enrollment.student_id]
                status = (
                    "absent"
                    if number == 0 and index % 5 != 0
                    else "excused"
                    if (index + number) % 11 == 0
                    else "late"
                    if (index + number) % 7 == 0
                    else "present"
                )
                rows[str(enrollment.pk)] = {
                    "status": "" if draft else status,
                    "notes": "Fictional approved excuse" if status == "excused" else "",
                }
            created = save_student_register(
                actor,
                year_id=year.pk,
                section_id=section.pk,
                day=day,
                rows=rows,
                final=not draft,
                reason="Fictional demonstration backfill",
            )
            created_register_ids.append(created.pk)
    closure_days = [
        event.starts_on
        for event in calendar.events
        if event.kind == "closure" and event.title.startswith("DEMO:")
    ]
    for index, day in enumerate(sorted(set(dates + closure_days))):
        if StaffRegister.objects.filter(academic_year=year, attendance_on=day).exists():
            continue
        rows, leave_keys = {}, approved_leave_keys(day)
        for key, person in staff_roster(day):
            # Never populate a register that would include an unrelated real employee.
            if not person.employee_number.startswith("DEMO-"):
                rows = {}
                break
            status = (
                "closure"
                if calendar.is_closure(day)
                else "leave"
                if key in leave_keys
                else "half_day"
                if person.pk == people[1].pk and key.startswith("staff:") and index % 5 == 1
                else "duty"
                if key.startswith("staff:") and index % 5 == 2
                else "absent"
                if key.startswith("teacher:") and index % 7 == 3
                else "late"
                if index % 6 == 4
                else "present"
            )
            rows[key] = {"status": status}
        if rows:
            save_staff_register(
                actor,
                year_id=year.pk,
                day=day,
                rows=rows,
                final=True,
                reason="Fictional staff demonstration backfill",
            )
    examples = [
        ("absent", "present", "approved"),
        ("late", "present", "rejected"),
        ("present", "late", "pending"),
    ]
    for before, after, decision in examples:
        reason = f"DEMO: {decision} fictional attendance correction"
        if AttendanceCorrection.objects.filter(reason=reason).exists():
            continue
        entry = (
            StudentAttendance.objects.filter(
                register_id__in=created_register_ids,
                student__in=students,
                register__academic_year=year,
                register__state="final",
                status=before,
            )
            .exclude(corrections__state="pending")
            .order_by("-attendance_on", "pk")
            .first()
        )
        if entry:
            correction = request_correction(
                actor, kind="student", entry_id=entry.pk, values={"status": after}, reason=reason
            )
            if decision != "pending":
                decide_correction(
                    reviewer,
                    correction.pk,
                    approve=decision == "approved",
                    reason="Fictional demonstration review",
                )
