"""Append examination examples only to the explicitly enabled fictional school seed."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError

from academics.models import ClassSubject, Subject, TeachingAssignment
from attendance.calendar import SchoolCalendar, school_now
from people.models import Enrollment

from .models import (
    Assessment,
    AssessmentType,
    ExamCandidate,
    ExamCohort,
    ExamController,
    ExamRoom,
    ExamSession,
    ExamSubject,
    GradeBand,
    GradingPolicy,
    MarkEntry,
    MarkSheet,
    SessionContribution,
)
from .services import (
    decide_correction,
    request_correction,
    review_sheet,
    save_marks,
    save_schedule,
    save_setup,
    school_zone,
    session_action,
    update_candidate,
)


def seed_examination_demo(accounts, year, students, sections):
    if year.status != "open" or year.name != "2026–2027":
        return
    expected = [
        ("Noor", "Meadow"),
        ("Mika", "Willow"),
        ("Arin", "Cedar"),
        ("Lina", "Brook"),
        ("Remy", "Haven"),
        ("Sora", "Fern"),
    ]
    if len(students) != 6 or any(
        (p.first_name, p.last_name) != expected[i] or p.admission_number != f"DEMO-{i + 1:04}"
        for i, p in enumerate(students)
    ):
        raise ValidationError(
            "Examination demonstration identifiers collide with existing students."
        )
    actor, controller, principal = (
        accounts["demo.admin"],
        accounts["demo.exams"],
        accounts["demo.principal"],
    )
    # Decline mixed real/demo rosters and non-demo controller identities.
    if any(not account.email.endswith("@example.invalid") for account in accounts.values()):
        raise ValidationError("Examination demonstrations require fictional accounts.")
    if (
        Enrollment.objects.filter(academic_year=year, section__in=sections)
        .exclude(student__in=students)
        .exists()
    ):
        return
    subject = Subject.objects.get(code="DEMO-MATH")
    for section in sections:
        ClassSubject.objects.get_or_create(
            academic_year=year, school_class=section.school_class, subject=subject
        )
    kinds = {}
    for name in (
        "Class test",
        "Weekly test",
        "Monthly test",
        "Unit test",
        "Midterm",
        "Final examination",
        "Practical",
        "Oral",
        "Coursework",
        "Supplementary",
    ):
        kinds[name], _ = AssessmentType.objects.get_or_create(
            name=f"DEMO · {name}",
            defaults={"description": "Fictional local demonstration assessment type"},
        )
    policy = GradingPolicy.objects.filter(
        academic_year=year, name="DEMO · Assessment policy v1"
    ).first()
    if policy is None:
        policy = save_setup(
            actor, GradingPolicy(academic_year=year, name="DEMO · Assessment policy v1")
        )
        for lower, upper, label, points in [
            (0, 50, "F", 0),
            (50, 60, "D", 1),
            (60, 70, "C", 2),
            (70, 80, "B", 3),
            (80, 90, "A", 4),
            (90, 100, "A+", 5),
        ]:
            save_setup(
                actor,
                GradeBand(
                    policy=policy,
                    lower=lower,
                    upper=upper,
                    label=label,
                    points=points,
                    description="Fictional example band",
                ),
            )
    room, _ = ExamRoom.objects.get_or_create(name="DEMO · Assessment room")
    term = year.terms.filter(name="Autumn").first()

    def action(session, name, who=actor):
        session.refresh_from_db()
        return session_action(
            who,
            session.pk,
            name,
            expected_version=session.version,
            reason="Fictional examination demonstration workflow",
        )

    created = {}
    specs = [
        ("Midterm", date(2026, 9, 7), "published"),
        ("Final examination", date(2026, 10, 5), "published"),
        ("Unit test", date(2026, 9, 21), "approved"),
        ("Weekly test", date(2026, 10, 12), "submitted"),
        ("Coursework", date(2026, 10, 19), "draft"),
    ]
    for name, start, target in specs:
        title = f"DEMO · {name} 2026"
        if (
            ExamSession.objects.filter(academic_year=year, name=title).exists()
            or start > school_now().date()
        ):
            continue
        session = save_setup(
            actor,
            ExamSession(
                academic_year=year,
                term=term,
                policy=policy,
                assessment_type=kinds[name],
                name=title,
                description="Fictional local demonstration; not a real school record.",
                starts_on=start,
                ends_on=start + timedelta(days=4),
                eligibility_on=start,
            ),
        )
        save_setup(actor, ExamController(session=session, user=controller))
        for section in sections:
            cohort = save_setup(actor, ExamCohort(session=session, section=section))
            exam_subject = save_setup(
                actor,
                ExamSubject(cohort=cohort, subject=subject, weight=100, passing_percentage=50),
            )
            for component, maximum, weight in [("Theory", 100, 70), ("Practical", 20, 30)]:
                assessment = save_setup(
                    actor,
                    Assessment(
                        exam_subject=exam_subject,
                        assessment_type=kinds[name]
                        if component == "Theory"
                        else kinds["Practical"],
                        name=component,
                        component=component.lower(),
                        max_marks=maximum,
                        weight=weight,
                    ),
                )
                # One room is intentionally used sequentially, avoiding class and duty conflicts.
                offset = sections.index(section) * 2 + (0 if component == "Theory" else 1)
                day = start + timedelta(days=offset // 4)
                if not SchoolCalendar(year).reason(day):
                    begin = datetime.combine(day, time(8 + offset % 4 * 2), school_zone())
                    save_schedule(
                        actor,
                        assessment_id=assessment.pk,
                        starts_at=begin,
                        ends_at=begin + timedelta(hours=1),
                        room=room,
                    )
        action(session, "open")
        for sheet in MarkSheet.objects.filter(
            assessment__exam_subject__cohort__session=session
        ).select_related("assessment__exam_subject__cohort"):
            cohort = sheet.assessment.exam_subject.cohort
            rows = {}
            for candidate in ExamCandidate.objects.filter(cohort=cohort).select_related("student"):
                index = next(i for i, p in enumerate(students) if p.pk == candidate.student_id)
                value = Decimal(45 + index * 7 + (8 if name == "Final examination" else 0))
                value = value / 100 * sheet.assessment.max_marks
                status, remarks = "assessed", "Keep building a consistent study routine."
                if name == "Final examination" and index == 4:
                    status, value, remarks = (
                        "absent",
                        None,
                        "Assessment missed; follow-up required.",
                    )
                if name == "Midterm" and index == 2 and sheet.assessment.component == "practical":
                    status, value, remarks = (
                        "exempt",
                        None,
                        "Authorized fictional practical exemption.",
                    )
                if (
                    name == "Final examination"
                    and index == 5
                    and sheet.assessment.component == "practical"
                ):
                    status, value, remarks = (
                        "incomplete",
                        None,
                        "Practical assessment awaiting completion.",
                    )
                rows[str(candidate.pk)] = {"status": status, "marks": value, "remarks": remarks}
            marking_actor = (
                accounts["demo.teacher"]
                if TeachingAssignment.objects.filter(
                    teacher__user=accounts["demo.teacher"],
                    academic_year=year,
                    section=cohort.section,
                    subject=subject,
                ).exists()
                else actor
            )
            sheet = save_marks(
                marking_actor, sheet.pk, rows, expected_version=0, submit=target != "draft"
            )
            if target in ("approved", "published"):
                review_sheet(
                    controller,
                    sheet.pk,
                    "approve",
                    expected_version=sheet.version,
                    reason="Independent fictional marks review",
                )
        for candidate in session.candidates.all():
            session.refresh_from_db()
            update_candidate(
                principal,
                candidate.pk,
                teacher_remarks="Steady effort will support continued progress.",
                principal_remarks="Reviewed for this fictional demonstration.",
                withheld=False,
                withholding_reason="",
                expected_version=session.version,
            )
        if target in ("approved", "published"):
            action(session, "close")
            action(session, "review", controller)
            action(session, "approve", principal)
        if target == "published":
            action(session, "publish")
        created[name] = session
    midterm = created.get("Midterm")
    if midterm:
        entry = MarkEntry.objects.filter(candidate__session=midterm, status="assessed").first()
        correction = request_correction(
            controller,
            entry.pk,
            status="assessed",
            marks=min(entry.marks + 1, entry.sheet.assessment.max_marks),
            remarks="Verified a credited response.",
            reason="Fictional rechecking example",
        )
        decide_correction(
            principal, correction.pk, approve=True, reason="Independent fictional recheck confirmed"
        )
    final = created.get("Final examination")
    if final:
        entries = list(
            MarkEntry.objects.filter(candidate__session=final, status="assessed").select_related(
                "sheet__assessment"
            )[:2]
        )
        for i, entry in enumerate(entries):
            correction = request_correction(
                controller,
                entry.pk,
                status="assessed",
                marks=max(entry.marks - 1, 0),
                remarks="Requested second review.",
                reason="Fictional correction request",
            )
            if i == 0:
                decide_correction(
                    principal,
                    correction.pk,
                    approve=False,
                    reason="Original award verified; no change",
                )
    sources = {
        name: ExamSession.objects.filter(
            academic_year=year, name=f"DEMO · {name} 2026", state="published"
        ).first()
        for name in ("Midterm", "Final examination")
    }
    title = "DEMO · Autumn performance 2026"
    if (
        term
        and all(sources.values())
        and not ExamSession.objects.filter(academic_year=year, name=title).exists()
    ):
        aggregate = save_setup(
            actor,
            ExamSession(
                academic_year=year,
                term=term,
                policy=policy,
                assessment_type=kinds["Monthly test"],
                name=title,
                report_kind="term",
                starts_on=date(2026, 10, 12),
                ends_on=date(2026, 10, 16),
                eligibility_on=date(2026, 10, 12),
            ),
        )
        save_setup(actor, ExamController(session=aggregate, user=controller))
        for section in sections:
            cohort = save_setup(actor, ExamCohort(session=aggregate, section=section))
            save_setup(actor, ExamSubject(cohort=cohort, subject=subject, weight=100))
        for name, weight in (("Midterm", 40), ("Final examination", 60)):
            save_setup(
                actor, SessionContribution(session=aggregate, source=sources[name], weight=weight)
            )
        action(aggregate, "open")
        action(aggregate, "close")
        action(aggregate, "review", controller)
        action(aggregate, "approve", principal)
        action(aggregate, "publish")
