import io
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase, override_settings
from django.urls import reverse

from academics.models import AcademicYear, Term
from audit.models import AuditEvent
from core.models import SchoolSettings
from core.uploads import private_document_path, validate_pdf
from people.models import Enrollment, GuardianStudent, Student

from .helpers import BACKEND, PASSWORD, make_school_data


class FoundationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.data = make_school_data()

    def test_health_checks_database_without_disclosing_details(self):
        response = self.client.get("/health/")
        self.assertEqual(response.json(), {"status": "ok"})
        with patch(
            "core.views.connection.cursor", side_effect=DatabaseError("private credentials")
        ):
            response = self.client.get("/health/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})

    def test_year_date_constraint(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            AcademicYear.objects.create(
                name="invalid",
                starts_on=self.data["year"].ends_on,
                ends_on=self.data["year"].starts_on,
            )

    def test_only_one_current_year(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            AcademicYear.objects.filter(pk=self.data["old_year"].pk).update(is_current=True)

    def test_term_must_be_inside_year(self):
        term = Term(
            academic_year=self.data["year"],
            name="Outside",
            starts_on=self.data["old_year"].starts_on,
            ends_on=self.data["old_year"].ends_on,
        )
        with self.assertRaises(ValidationError):
            term.full_clean()

    def test_duplicate_active_enrollment_is_rejected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Enrollment.objects.create(
                student=self.data["own"],
                academic_year=self.data["year"],
                section=self.data["other_section"],
                started_on=self.data["year"].starts_on,
            )

    def test_class_transfer_retains_history(self):
        previous = Enrollment.objects.get(student=self.data["own"], academic_year=self.data["year"])
        previous.is_active = False
        previous.ended_on = previous.started_on + timedelta(days=20)
        previous.full_clean()
        previous.save()
        current = Enrollment(
            student=self.data["own"],
            academic_year=self.data["year"],
            section=self.data["other_section"],
            started_on=previous.ended_on + timedelta(days=1),
        )
        current.full_clean()
        current.save()
        self.assertEqual(
            Enrollment.objects.filter(
                student=self.data["own"], academic_year=self.data["year"]
            ).count(),
            2,
        )

    def test_overlapping_enrollment_is_rejected_by_validation(self):
        row = Enrollment(
            student=self.data["own"],
            academic_year=self.data["year"],
            section=self.data["other_section"],
            started_on=self.data["year"].starts_on,
            ended_on=self.data["year"].starts_on + timedelta(days=3),
            is_active=False,
        )
        with self.assertRaises(ValidationError):
            row.full_clean()

    def test_academic_references_are_protected(self):
        with self.assertRaises(ProtectedError):
            self.data["section"].delete()

    def test_guardian_link_is_unique(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            GuardianStudent.objects.create(
                guardian=self.data["guardian"], student=self.data["own"], relationship="Duplicate"
            )

    def test_deleting_account_retains_profile_and_audit(self):
        user = self.data["student_user"]
        AuditEvent.objects.create(actor=user, event="test.retained")
        user.delete()
        self.data["own"].refresh_from_db()
        self.assertIsNone(self.data["own"].user_id)
        self.assertIsNone(AuditEvent.objects.get(event="test.retained").actor_id)

    def test_settings_require_permission_and_validate_timezone(self):
        self.client.force_login(self.data["student_user"], backend=BACKEND)
        self.assertEqual(self.client.get(reverse("core:school_settings")).status_code, 403)
        self.client.force_login(self.data["admin"], backend=BACKEND)
        response = self.client.post(
            reverse("core:school_settings"),
            {"name": "Fictional School", "timezone": "Not/AZone", "currency": "PKR"},
        )
        self.assertContains(response, "valid IANA timezone")
        self.assertFalse(SchoolSettings.objects.exists())
        response = self.client.post(
            reverse("core:school_settings"),
            {"name": "Fictional School", "timezone": "Asia/Karachi", "currency": "PKR"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(SchoolSettings.objects.get().name, "Fictional School")
        self.assertTrue(AuditEvent.objects.filter(event="school.settings_changed").exists())

    def test_school_settings_singleton_constraint(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            SchoolSettings.objects.create(pk=2)

    def test_audit_view_requires_permission(self):
        self.client.force_login(self.data["admin"], backend=BACKEND)
        self.assertEqual(self.client.get("/audit/").status_code, 403)

    def test_planned_modules_and_unknown_module(self):
        self.client.force_login(self.data["student_user"], backend=BACKEND)
        self.assertContains(self.client.get("/modules/"), "planned")
        self.assertContains(self.client.get("/modules/finance/"), "no records or actions")
        self.assertEqual(self.client.get("/modules/not-real/").status_code, 404)

    def test_pdf_boundary_rejects_mismatched_file_and_keeps_private_path(self):
        validate_pdf(SimpleUploadedFile("valid.pdf", b"%PDF-1.7\nfictional"))
        for name, content in [
            ("bad.svg", b"%PDF-1.7"),
            ("bad.pdf", b"<script>"),
            ("big.pdf", b"%PDF-" + b"x" * (2 * 1024 * 1024)),
        ]:
            with self.subTest(name=name), self.assertRaises(ValidationError):
                validate_pdf(SimpleUploadedFile(name, content))
        path = private_document_path(None, "../../student-name.pdf")
        self.assertTrue(path.startswith("private/documents/"))
        self.assertNotIn("student-name", path)

    def test_demo_seed_is_disabled_by_default(self):
        with self.assertRaises(CommandError):
            call_command("seed_demo", stdout=io.StringIO())

    @override_settings(DEBUG=True, ALLOW_DEMO_DATA=True)
    def test_demo_seed_is_repeatable_and_preserves_passwords(self):
        with patch.dict("os.environ", {"DEMO_PASSWORD": PASSWORD}):
            call_command("seed_demo", stdout=io.StringIO())
            users = get_user_model().objects.count()
            students = Student.objects.count()
            user = get_user_model().objects.get(username="demo.student")
            user.set_password("Changed-Fictional-Passphrase-123!")
            user.save()
            call_command("seed_demo", stdout=io.StringIO())
        self.assertEqual(get_user_model().objects.count(), users)
        self.assertEqual(Student.objects.count(), students)
        user.refresh_from_db()
        self.assertTrue(user.check_password("Changed-Fictional-Passphrase-123!"))
        self.assertFalse(user.is_staff or user.is_superuser)

    @override_settings(DEBUG=False, ALLOW_DEMO_DATA=True)
    def test_demo_seed_refuses_production_even_with_flag(self):
        with self.assertRaises(CommandError):
            call_command("seed_demo", stdout=io.StringIO())

    def test_sync_roles_is_idempotent(self):
        from django.contrib.auth.models import Group

        call_command("sync_roles", stdout=io.StringIO())
        count = Group.objects.count()
        call_command("sync_roles", stdout=io.StringIO())
        self.assertEqual(Group.objects.count(), count)
