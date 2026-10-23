from datetime import time, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction

from academics.models import TeachingAssignment
from attendance.calendar import school_now
from communications.models import Conversation, Publication
from communications.services import publication_action, save_publication, send
from learning.models import Assignment
from learning.services import review, save_assignment, submit
from learning.services import transition as publish_work
from people.models import Teacher
from scheduling.models import Entry, Period, Room, Timetable
from scheduling.services import save_entry, substitute
from scheduling.services import transition as publish_table


@transaction.atomic
def seed_teaching_demo(accounts, year, students, sections):
    if not settings.DEBUG or not settings.ALLOW_DEMO_DATA:
        raise ValidationError("Teaching demonstrations require explicit local demo mode.")
    if any(not s.admission_number.startswith("DEMO-") for s in students) or any(
        not u.email.endswith("@example.invalid") for u in accounts.values()
    ):
        raise ValidationError("Only verified fictional school identities may be used.")
    now = school_now()
    if not year.starts_on <= now.date() <= year.ends_on:
        return
    admin, teacher = accounts["demo.admin"], accounts["demo.teacher"]
    assigned = (
        TeachingAssignment.objects.filter(teacher__user=teacher, academic_year=year)
        .select_related("teacher")
        .order_by("section_id")
    )
    first = assigned.filter(section=sections[0]).get()
    room, _ = Room.objects.get_or_create(name="DEMO Learning Studio")
    table = Timetable.objects.filter(title="DEMO Weekly Learning").first()
    if table is None:
        start = max(now.date(), year.starts_on)
        end = min(start + timedelta(days=20), year.ends_on)
        table = Timetable.objects.create(
            title="DEMO Weekly Learning", academic_year=year, starts_on=start, ends_on=end
        )
        revision = 1
        for weekday in range(5):
            for index, assignment in enumerate(assigned):
                period, _ = Period.objects.get_or_create(
                    academic_year=year,
                    shift="DEMO Day",
                    name=f"DEMO Lesson {index + 1}",
                    weekday=weekday,
                    defaults={"starts_at": time(8 + index), "ends_at": time(8 + index, 40)},
                )
                row = Entry(timetable=table, period=period, assignment=assignment, room=room)
                try:
                    with transaction.atomic():
                        save_entry(admin, row, revision)
                except ValidationError:
                    continue  # Existing approved leave/closures remain authoritative.
                revision += 1
        if table.entries.exists():
            publish_table(admin, table.pk, "publish")
            entry = table.entries.first()
            from scheduling.services import dates

            days = dates(table, entry.period)
            alternate, _ = Teacher.objects.get_or_create(
                employee_number="DEMO-T002",
                defaults={
                    "first_name": "Morgan",
                    "last_name": "Brook",
                    "joined_on": year.starts_on,
                },
            )
            TeachingAssignment.objects.get_or_create(
                teacher=alternate, academic_year=year, section=sections[0], subject=first.subject
            )
            if days:
                substitute(
                    admin, entry.pk, days[0], alternate, "Fictional cover arrangement", approve=True
                )
    labels = [
        ("DEMO Fractions practice", False, False),
        ("DEMO Reading reflection", False, True),
        ("DEMO Late project reflection", True, True),
    ]
    for title, late, submitted in labels:
        if Assignment.objects.filter(title=title, teaching=first).exists():
            continue
        work = Assignment(
            teaching=first,
            title=title,
            description=(
                "Use a familiar everyday example. Explain your reasoning in your own words."
            ),
            publish_at=now - timedelta(days=2),
            due_at=now - timedelta(hours=1) if late else now + timedelta(days=3),
            maximum=100,
            # Submitted demonstration work must remain seedable at timezone/date
            # boundaries; production assignments still enforce their configured
            # late-submission policy in ``learning.services.submit``.
            late_allowed=late or submitted,
            late_penalty=10 if late else 0,
        )
        save_assignment(teacher, work)
        publish_work(teacher, work.pk, "publish")
        if submitted:
            row = submit(
                accounts["demo.student"],
                work.pk,
                "Fictional response: I divided the whole into equal parts.",
                final=True,
            )
            review(
                teacher,
                row.pk,
                text="Clear explanation. Add a labelled diagram next time.",
                outcome="graded",
                marks=80,
                released=True,
                guardian_visible=True,
            )
    for kind, title in [
        ("event", "DEMO Parent-teacher learning evening"),
        ("announcement", "DEMO Welcome to the learning week"),
    ]:
        if Publication.objects.filter(title=title).exists():
            continue
        row = Publication(
            kind=kind,
            title=title,
            body="A fictional opportunity to share progress, ask questions and celebrate learning.",
            author=admin,
            publish_at=now - timedelta(minutes=1),
            starts_at=now + timedelta(days=4) if kind == "event" else None,
            ends_at=now + timedelta(days=4, hours=1) if kind == "event" else None,
            location="DEMO Learning Studio" if kind == "event" else "",
        )
        save_publication(admin, row)
        publication_action(accounts["demo.principal"], row.pk, "publish")
    if not Conversation.objects.filter(subject="DEMO Learning progress").exists():
        row = send(
            teacher,
            "Avery has made a thoughtful start to the learning week.",
            recipient=accounts["demo.parent"],
            student=students[0],
            subject="DEMO Learning progress",
        )
        send(
            accounts["demo.parent"],
            "Thank you. We will look over the feedback together.",
            conversation=row.pk,
        )
