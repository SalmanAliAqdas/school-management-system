"""Portal composition only; domain calculations remain in the owning modules."""

from datetime import timedelta

from django.db.models import F, Window
from django.db.models.functions import RowNumber
from django.urls import reverse

from academics.models import Term
from attendance.calendar import SchoolCalendar, school_now
from attendance.reporting import student_summaries
from attendance.selectors import student_entries_visible_to
from examinations.models import ExamSchedule
from examinations.reporting import current_results
from examinations.selectors import sessions_visible_to
from finance.ledger import student_balance_map
from finance.selectors import invoices_visible_to
from people.models import Enrollment


def latest_per_student(rows, field, *, limit=1):
    return rows.annotate(
        portal_rank=Window(
            expression=RowNumber(),
            partition_by=[F(field)],
            order_by=[F("created_at").desc(), F("pk").desc()],
        )
    ).filter(portal_rank__lte=limit)


def child_summaries(user, children, year, today, *, role):
    """Query count is independent of the number of children on a bounded page."""
    children = list(children)
    ids = [child.pk for child in children]
    placements = {
        row.student_id: row
        for row in Enrollment.objects.filter(
            student_id__in=ids, is_active=True, academic_year=year, started_on__lte=today
        ).select_related("section__school_class", "academic_year")
    }
    attendance, recorded_today = {}, {}
    if year:
        calendar = SchoolCalendar(year)
        dates = calendar.working_dates(today.replace(day=1), today)
        rows = student_entries_visible_to(user).filter(
            student_id__in=ids, register__academic_year=year
        )
        attendance = {
            r["student_id"]: r for r in student_summaries(rows.filter(attendance_on__in=dates))
        }
        recorded_today = {r.student_id: r for r in rows.filter(attendance_on=today)}
    results = {}
    rows = (
        current_results(user)
        .filter(candidate__student_id__in=ids, candidate__withheld=False)
        .exclude(data__outcome="withheld")
    )
    for row in latest_per_student(rows, "candidate__student_id"):
        results[row.candidate.student_id] = row
    from .selectors import personal_finance_students

    authorized = list(
        personal_finance_students(user, role).filter(pk__in=ids).values_list("pk", flat=True)
    )
    recent_invoices = {
        row.student_id: row
        for row in latest_per_student(
            invoices_visible_to(user).filter(
                student_id__in=authorized, state__in=["issued", "voided"]
            ),
            "student_id",
        )
    }
    balances = student_balance_map(authorized)
    return [
        {
            "student": child,
            "placement": placements.get(child.pk),
            "attendance": attendance.get(child.pk),
            "today": recorded_today.get(child.pk),
            "result": results.get(child.pk),
            "balance": balances.get(child.pk),
            "invoice": recent_invoices.get(child.pk),
        }
        for child in children
    ]


def schedules_for(user, student):
    return (
        ExamSchedule.objects.filter(
            assessment__exam_subject__cohort__session__in=sessions_visible_to(user),
            assessment__exam_subject__cohort__candidates__student=student,
        )
        .exclude(assessment__exam_subject__cohort__session__state="draft")
        .select_related(
            "assessment__exam_subject__subject", "assessment__exam_subject__cohort__session", "room"
        )
        .distinct()
    )


def calendar_items(user, year, *, student=None, teacher=False, role=None):
    if not year:
        return []
    items = []
    zone = school_now().tzinfo
    for term in Term.objects.filter(academic_year=year):
        for label, day in (("begins", term.starts_on), ("ends", term.ends_on)):
            items.append(
                {"date": day, "title": f"{term.name} {label}", "category": "Academic term"}
            )
    calendar = SchoolCalendar(year)
    for event in calendar.events:
        if event.applies_to in ("both", "staff" if teacher else "students"):
            items.append(
                {
                    "date": event.starts_on,
                    "end": event.ends_on,
                    "title": event.title,
                    "category": event.get_kind_display(),
                    "url": reverse(
                        "attendance:staff_dashboard" if teacher else "attendance:student",
                        args=[] if teacher else [student.pk],
                    ),
                }
            )
    if student:
        for slot in schedules_for(user, student).filter(
            assessment__exam_subject__cohort__session__academic_year=year
        )[:150]:
            session = slot.assessment.exam_subject.cohort.session
            items.append(
                {
                    "date": slot.starts_at.astimezone(zone).date(),
                    "title": f"{session.name} · {slot.assessment.exam_subject.subject}",
                    "category": "Examination",
                    "url": reverse("examinations:schedules"),
                }
            )
        from .selectors import personal_finance_students

        for invoice in (
            invoices_visible_to(user)
            .filter(
                student=student,
                student__in=personal_finance_students(user, role),
                academic_year=year,
                state="issued",
            )
            .order_by("due_on")[:150]
        ):
            items.append(
                {
                    "date": invoice.due_on,
                    "title": f"Invoice {invoice.number} due",
                    "category": "Fee due date",
                    "url": reverse("finance:invoice", args=[invoice.pk]),
                }
            )
    if teacher:
        from django.db.models import Exists, OuterRef

        from .selectors import assignments, teacher_sheets

        own = assignments(user).filter(academic_year=year)
        sheets = teacher_sheets(user, own)
        matching = own.filter(
            section_id=OuterRef("section_id"),
            subject_id=OuterRef("assessment__exam_subject__subject_id"),
        )
        slots = (
            ExamSchedule.objects.filter(assessment__sheet__in=sheets)
            .alias(portal_assigned=Exists(matching))
            .filter(portal_assigned=True)
            .select_related("assessment__exam_subject__subject")
        )
        for slot in slots[:150]:
            items.append(
                {
                    "date": slot.starts_at.astimezone(zone).date(),
                    "title": f"{slot.assessment.exam_subject.subject} examination",
                    "category": "Examination",
                    "url": reverse("examinations:schedules"),
                }
            )
    return sorted(items, key=lambda item: (item["date"], item["title"]))


def attendance_trend(user, student, year):
    from attendance.reporting import monthly_trends

    if not year:
        return []
    calendar = SchoolCalendar(year)
    dates = calendar.working_dates(year.starts_on, min(school_now().date(), year.ends_on))
    rows = student_entries_visible_to(user).filter(
        student=student, register__academic_year=year, attendance_on__in=dates
    )
    return monthly_trends(rows)


def month_end(day):
    return (day.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
