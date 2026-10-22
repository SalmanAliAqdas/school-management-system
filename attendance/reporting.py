import calendar as month_calendar
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import Case, Count, DecimalField, F, Q, Sum, Value, When
from django.db.models.functions import Coalesce, TruncMonth

from .calendar import SchoolCalendar, school_now
from .selectors import staff_entries_visible_to, student_entries_visible_to


def report_range(data):
    year = data["academic_year"]
    day = data.get("date") or school_now().date()
    period = data.get("period") or "month"
    if period == "year":
        start, end = year.starts_on, year.ends_on
    elif period == "day":
        start = end = day
    elif period == "week":
        start = day - timedelta(days=day.weekday())
        end = start + timedelta(days=6)
    elif period == "custom":
        start, end = data.get("starts_on"), data.get("ends_on")
        if not start or not end:
            raise ValidationError("Choose a start and end date for a custom report.")
    else:
        start = day.replace(day=1)
        end = day.replace(day=month_calendar.monthrange(day.year, day.month)[1])
    if end < start or (end - start).days > 731:
        raise ValidationError("Choose an ordered report range of at most two years.")
    return max(start, year.starts_on), min(end, year.ends_on)


def metric_expressions(*, staff=False):
    decimal = DecimalField(max_digits=12, decimal_places=4)
    earned = [
        When(status="present", then=Value(Decimal(1))),
        When(status="late", then=F("register__policy__late_credit")),
    ]
    if staff:
        earned += [
            When(status="duty", then=Value(Decimal(1))),
            When(status="half_day", then=Value(Decimal("0.5"))),
        ]
        excluded = Q(status__in=["leave", "closure", ""])
    else:
        excluded = Q(status="excused", register__policy__exclude_excused=True) | Q(status="")
    metrics = {
        name: Count("pk", filter=Q(status=name))
        for name in ["present", "absent", "late", "excused", "half_day", "leave", "duty", "closure"]
    }
    metrics.update(
        total=Count("pk"),
        credit=Coalesce(
            Sum(Case(*earned, default=Value(Decimal(0)), output_field=decimal)),
            Value(Decimal(0)),
            output_field=decimal,
        ),
        denominator=Count("pk", filter=~excluded),
    )
    return metrics


def add_percentage(result):
    result["percentage"] = (
        (Decimal(result["credit"]) * 100 / result["denominator"]).quantize(Decimal("0.01"))
        if result["denominator"]
        else None
    )
    return result


def summary(rows, *, staff=False):
    return add_percentage(rows.aggregate(**metric_expressions(staff=staff)))


def report_rows(actor, data, *, staff=False):
    year = data["academic_year"]
    start, end = report_range(data)
    calendar = SchoolCalendar(year)
    dates = calendar.working_dates(start, end, staff=staff)
    rows = staff_entries_visible_to(actor) if staff else student_entries_visible_to(actor)
    rows = rows.filter(register__academic_year=year, attendance_on__in=dates)
    if not staff:
        if data.get("school_class"):
            rows = rows.filter(register__section__school_class=data["school_class"])
        if data.get("section"):
            rows = rows.filter(register__section=data["section"])
        if data.get("student"):
            rows = rows.filter(student=data["student"])
    if data.get("status"):
        rows = rows.filter(status=data["status"])
    if staff and data.get("employee"):
        kind, pk = data["employee"].split(":", 1)
        rows = rows.filter(**{f"{kind}_id": int(pk)})
    if staff and data.get("department"):
        rows = rows.filter(
            Q(teacher__department__iexact=data["department"])
            | Q(staff__department__iexact=data["department"])
        )
    if data.get("q"):
        q = data["q"]
        names = (
            Q(teacher__first_name__icontains=q)
            | Q(teacher__last_name__icontains=q)
            | Q(staff__first_name__icontains=q)
            | Q(staff__last_name__icontains=q)
            if staff
            else Q(student__first_name__icontains=q)
            | Q(student__last_name__icontains=q)
            | Q(student__admission_number__icontains=q)
        )
        rows = rows.filter(names)
    return rows, start, end, calendar


def student_summaries(rows):
    groups = (
        rows.values(
            "student_id", "student__first_name", "student__last_name", "student__admission_number"
        )
        .annotate(**metric_expressions())
        .order_by("student__first_name", "student_id")
    )
    return [add_percentage(row) for row in groups]


def class_summaries(rows):
    groups = (
        rows.values(
            "register__section_id",
            "register__section__name",
            "register__section__school_class__name",
        )
        .annotate(**metric_expressions())
        .order_by("register__section__school_class__sort_order", "register__section__name")
    )
    return [add_percentage(row) for row in groups]


def staff_summaries(rows):
    groups = (
        rows.values("teacher_id", "staff_id")
        .annotate(
            first_name=Coalesce("teacher__first_name", "staff__first_name"),
            last_name=Coalesce("teacher__last_name", "staff__last_name"),
            department=Coalesce("teacher__department", "staff__department"),
            **metric_expressions(staff=True),
        )
        .order_by("first_name", "teacher_id", "staff_id")
    )
    return [add_percentage(row) for row in groups]


def department_summaries(rows):
    groups = (
        rows.annotate(department_name=Coalesce("teacher__department", "staff__department"))
        .values("department_name")
        .annotate(**metric_expressions(staff=True))
        .order_by("department_name")
    )
    return [add_percentage(row) for row in groups]


def daily_trends(rows, *, staff=False):
    return [
        add_percentage(row)
        for row in rows.values("attendance_on")
        .annotate(**metric_expressions(staff=staff))
        .order_by("attendance_on")
    ]


def monthly_trends(rows, *, staff=False):
    return [
        add_percentage(row)
        for row in rows.annotate(month=TruncMonth("attendance_on"))
        .values("month")
        .annotate(**metric_expressions(staff=staff))
        .order_by("month")
    ]


def month_cells(year, month_day, records, placements, calendar, *, staff=False, person=None):
    first = month_day.replace(day=1)
    count = month_calendar.monthrange(first.year, first.month)[1]
    by_day = {entry.attendance_on: entry for entry in records}
    today = school_now().date()
    cells = [None] * first.weekday()
    for number in range(1, count + 1):
        day = first.replace(day=number)
        entry = by_day.get(day)
        exclusion = calendar.reason(day, staff=staff)
        eligible = (
            person.joined_on <= day and (person.left_on is None or person.left_on >= day)
            if staff
            else any(
                row.started_on <= day and (row.ended_on is None or row.ended_on >= day)
                for row in placements
            )
        )
        if exclusion:
            label, state = exclusion, "excluded"
        elif entry:
            label, state = entry.get_status_display(), entry.status
        elif not eligible:
            label, state = "Outside enrollment" if not staff else "Outside employment", "excluded"
        elif day > today:
            label, state = "Upcoming", "upcoming"
        else:
            label, state = "Not recorded", "missing"
        cells.append(
            {
                "day": day,
                "label": label,
                "state": state,
                "entry": entry,
                "excluded": bool(exclusion),
            }
        )
    return cells
