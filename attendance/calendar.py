from datetime import timedelta
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.utils import timezone

from core.models import SchoolSettings

from .models import AttendancePolicy, CalendarEvent


def school_now():
    zone = SchoolSettings.objects.values_list("timezone", flat=True).first() or "Asia/Karachi"
    return timezone.now().astimezone(ZoneInfo(zone))


def policy_on(year, day):
    policy = AttendancePolicy.objects.filter(academic_year=year, effective_from__lte=day).first()
    if not policy:
        raise ValidationError("Configure an attendance policy effective on this date first.")
    return policy


class SchoolCalendar:
    """Load a year's rules once; date expansion does not issue queries per day/student."""

    def __init__(self, year):
        self.year = year
        self.policies = list(AttendancePolicy.objects.filter(academic_year=year))
        self.events = list(CalendarEvent.objects.filter(academic_year=year, is_cancelled=False))
        self.terms = list(year.terms.values_list("starts_on", "ends_on"))

    def policy(self, day):
        return next((p for p in self.policies if p.effective_from <= day), None)

    def reason(self, day, *, staff=False):
        if not self.year.starts_on <= day <= self.year.ends_on:
            return "Outside academic year"
        policy = self.policy(day)
        if not policy:
            return "Attendance policy not configured"
        events = [
            event
            for event in self.events
            if event.applies_to in ("both", "staff" if staff else "students")
            and event.starts_on <= day <= event.ends_on
        ]
        closed = next((event for event in events if event.kind != "working"), None)
        if closed:
            return closed.title
        if (
            not staff
            and policy.enforce_terms
            and self.terms
            and not any(start <= day <= end for start, end in self.terms)
        ):
            return "Outside academic terms"
        if any(event.kind == "working" for event in events):
            return ""
        return "Weekly holiday" if day.weekday() not in policy.working_weekdays else ""

    def is_closure(self, day):
        return any(
            event.kind == "closure"
            and event.applies_to in ("both", "staff")
            and event.starts_on <= day <= event.ends_on
            for event in self.events
        )

    def working_dates(self, start, end, *, staff=False):
        start, end = max(start, self.year.starts_on), min(end, self.year.ends_on)
        return [
            start + timedelta(days=i)
            for i in range(max(0, (end - start).days + 1))
            if not self.reason(start + timedelta(days=i), staff=staff)
        ]
