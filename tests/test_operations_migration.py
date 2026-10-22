from datetime import date

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class OperationsMigrationTests(TransactionTestCase):
    def test_upgrade_preserves_legacy_admissions_and_assignments(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        before = [("people", "0001_initial"), ("academics", "0002_initial")]
        try:
            executor.migrate(before)
            apps = executor.loader.project_state(before).apps
            year = apps.get_model("academics", "AcademicYear").objects.create(
                name="Legacy year", starts_on=date(2025, 8, 1), ends_on=date(2026, 7, 31)
            )
            grade = apps.get_model("academics", "SchoolClass").objects.create(name="Legacy class")
            section = apps.get_model("academics", "Section").objects.create(
                school_class=grade, name="A"
            )
            student = apps.get_model("people", "Student").objects.create(
                first_name="Legacy",
                last_name="Learner",
                admission_number="LEGACY-001",
                is_active=False,
            )
            enrollment = apps.get_model("people", "Enrollment").objects.create(
                student=student,
                academic_year=year,
                section=section,
                started_on=year.starts_on,
                ended_on=year.ends_on,
                is_active=False,
            )
            teacher = apps.get_model("people", "Teacher").objects.create(
                first_name="Legacy", last_name="Teacher", employee_number="LEGACY-T1"
            )
            subject = apps.get_model("academics", "Subject").objects.create(
                code="LEG-M", name="Math"
            )
            apps.get_model("academics", "TeachingAssignment").objects.create(
                teacher=teacher, academic_year=year, section=section, subject=subject
            )
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
        from academics.models import ClassSubject
        from people.models import Enrollment, Student

        upgraded = Student.objects.get(pk=student.pk)
        self.assertEqual(upgraded.admission_number, "LEGACY-001")
        self.assertEqual(upgraded.admission_date, date(2025, 8, 1))
        self.assertEqual(upgraded.status, "withdrawn")
        self.assertEqual(Enrollment.objects.get(pk=enrollment.pk).section_id, section.pk)
        self.assertTrue(
            ClassSubject.objects.filter(
                academic_year_id=year.pk, school_class_id=grade.pk, subject_id=subject.pk
            ).exists()
        )
