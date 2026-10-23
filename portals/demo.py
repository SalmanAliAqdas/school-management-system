"""Additive examples for the explicitly gated fictional demonstration school."""

from datetime import date

from django.conf import settings
from django.core.exceptions import ValidationError

from academics.models import AcademicYear, Subject, TeachingAssignment
from academics.services import period_action
from people.models import Enrollment, GuardianStudent, Teacher


def seed_portal_demo(accounts, year, students, sections):
    if not settings.DEBUG or not settings.ALLOW_DEMO_DATA:
        raise ValidationError("Portal demonstrations require explicit local demo mode.")
    if len(students) != 6 or any(not p.admission_number.startswith("DEMO-") for p in students):
        raise ValidationError("Portal examples require the verified fictional school.")
    if any(not user.email.endswith("@example.invalid") for user in accounts.values()):
        raise ValidationError("Portal examples require fictional identities.")
    teacher = Teacher.objects.get(user=accounts["demo.teacher"], employee_number="DEMO-T001")
    subject = Subject.objects.get(code="DEMO-MATH")
    guardian = students[0].guardian_links.get(guardian__user=accounts["demo.parent"]).guardian
    GuardianStudent.objects.get_or_create(
        guardian=guardian, student=students[1], defaults={"relationship": "Guardian"}
    )
    # The third section already contains a draft register; no new attendance is fabricated.
    TeachingAssignment.objects.get_or_create(
        teacher=teacher, academic_year=year, section=sections[2], subject=subject
    )
    old, created = AcademicYear.objects.get_or_create(
        name="DEMO 2025–2026 history",
        defaults={
            "starts_on": date(2025, 8, 1),
            "ends_on": date(2026, 7, 31),
            "status": "open",
        },
    )
    if old.starts_on != date(2025, 8, 1) or old.ends_on != date(2026, 7, 31):
        raise ValidationError("Historical demonstration year collides with existing configuration.")
    for index, student in enumerate(students[:2]):
        Enrollment.objects.get_or_create(
            student=student,
            academic_year=old,
            section=sections[index],
            defaults={"started_on": old.starts_on, "ended_on": old.ends_on, "is_active": False},
        )
    if created and teacher.joined_on <= old.ends_on:
        TeachingAssignment.objects.get_or_create(
            teacher=teacher, academic_year=old, section=sections[0], subject=subject
        )
    if created:
        period_action(accounts["demo.admin"], "years", old.pk, "close")
        period_action(accounts["demo.admin"], "years", old.pk, "archive")
