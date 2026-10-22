import os
from datetime import date

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from academics.models import AcademicYear, SchoolClass, Section, Subject, TeachingAssignment, Term
from accounts.roles import sync_roles
from audit.services import record_event
from core.models import SchoolSettings
from people.models import Enrollment, Guardian, GuardianStudent, Staff, Student, Teacher


class Command(BaseCommand):
    help = "Initialize fictional demo records. Requires DEBUG, ALLOW_DEMO_DATA and DEMO_PASSWORD."

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG or not settings.ALLOW_DEMO_DATA:
            raise CommandError("Demo data is disabled. Enable only in explicit local development.")
        password = os.getenv("DEMO_PASSWORD", "")
        if not password:
            raise CommandError(
                "Set DEMO_PASSWORD in the local environment; do not pass it as an argument."
            )
        try:
            validate_password(password)
        except ValidationError as exc:
            raise CommandError(
                "DEMO_PASSWORD does not meet the configured password policy."
            ) from exc
        sync_roles()
        school, _ = SchoolSettings.objects.get_or_create(
            pk=1, defaults={"name": "RumiWare Demonstration School"}
        )
        year, _ = AcademicYear.objects.get_or_create(
            name="2026–2027",
            defaults={
                "starts_on": date(2026, 8, 1),
                "ends_on": date(2027, 7, 31),
                "is_current": not AcademicYear.objects.filter(is_current=True).exists(),
            },
        )
        Term.objects.get_or_create(
            academic_year=year,
            name="Autumn",
            defaults={
                "starts_on": date(2026, 8, 1),
                "ends_on": date(2026, 12, 31),
            },
        )
        sections = []
        for number in (6, 7, 8):
            school_class, _ = SchoolClass.objects.get_or_create(
                name=f"Grade {number}", defaults={"sort_order": number}
            )
            section, _ = Section.objects.get_or_create(school_class=school_class, name="A")
            sections.append(section)
        subject, _ = Subject.objects.get_or_create(
            code="DEMO-MATH", defaults={"name": "Mathematics"}
        )
        identities = [
            ("demo.admin", "Alex", "Morgan", "System Administrator"),
            ("demo.principal", "Robin", "Vale", "Principal"),
            ("demo.schooladmin", "Sam", "River", "School Administrator"),
            ("demo.accountant", "Taylor", "Stone", "Accountant"),
            ("demo.exams", "Casey", "Brooks", "Examination Controller"),
            ("demo.teacher", "Avery", "Reed", "Teacher"),
            ("demo.student", "Noor", "Meadow", "Student"),
            ("demo.parent", "Rowan", "Meadow", "Parent or Guardian"),
            ("demo.hr", "Jordan", "Ellis", "HR Manager"),
            ("demo.librarian", "Finley", "Sage", "Librarian"),
            ("demo.transport", "River", "Lane", "Transport Manager"),
        ]
        accounts = {}
        for username, first, last, role in identities:
            account, created = get_user_model().objects.get_or_create(
                username=username,
                defaults={
                    "email": f"{username}@example.invalid",
                    "first_name": first,
                    "last_name": last,
                },
            )
            if not created and not account.email.endswith("@example.invalid"):
                raise CommandError(f"Refusing to alter a non-demo account: {username}")
            # Re-running never resets an existing account's password or elevates staff status.
            if created:
                account.set_password(password)
                account.save()
            account.groups.add(Group.objects.get(name=role))
            accounts[username] = account
        teacher, _ = Teacher.objects.get_or_create(
            employee_number="DEMO-T001",
            defaults={
                "user": accounts["demo.teacher"],
                "first_name": "Avery",
                "last_name": "Reed",
            },
        )
        for section in sections[:2]:
            TeachingAssignment.objects.get_or_create(
                teacher=teacher, academic_year=year, section=section, subject=subject
            )
        names = [
            ("Noor", "Meadow"),
            ("Mika", "Willow"),
            ("Arin", "Cedar"),
            ("Lina", "Brook"),
            ("Remy", "Haven"),
            ("Sora", "Fern"),
        ]
        students = []
        for index, (first, last) in enumerate(names):
            student, _ = Student.objects.get_or_create(
                admission_number=f"DEMO-{index + 1:04}",
                defaults={
                    "first_name": first,
                    "last_name": last,
                    "user": accounts["demo.student"] if index == 0 else None,
                },
            )
            Enrollment.objects.get_or_create(
                student=student,
                academic_year=year,
                section=sections[index % 3],
                defaults={"started_on": year.starts_on},
            )
            students.append(student)
        guardian, _ = Guardian.objects.get_or_create(
            user=accounts["demo.parent"], defaults={"first_name": "Rowan", "last_name": "Meadow"}
        )
        GuardianStudent.objects.get_or_create(
            guardian=guardian, student=students[0], defaults={"relationship": "Guardian"}
        )
        Staff.objects.get_or_create(
            employee_number="DEMO-S001",
            defaults={
                "user": accounts["demo.schooladmin"],
                "first_name": "Sam",
                "last_name": "River",
                "job_title": "School administrator",
            },
        )
        from attendance.demo import seed_attendance_demo

        seed_attendance_demo(accounts, year, students, sections)
        record_event("demo.initialized", target=school.pk)
        self.stdout.write(
            self.style.SUCCESS("Fictional demo initialized; existing passwords preserved.")
        )
        for username, _first, _last, role in identities:
            self.stdout.write(f"{username} - {role}")
