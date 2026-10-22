import csv
import io
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from academics.forms import ACADEMIC_FORMS
from academics.models import (
    AcademicYear,
    ClassSubject,
    SchoolClass,
    Section,
    Term,
)
from academics.services import period_action, save_academic
from audit.models import AuditEvent
from core.uploads import sanitize_image
from people.forms import GuardianLinkForm
from people.imports import CSV_COLUMNS, confirm_import, preview_import
from people.models import AdmissionImport, Enrollment, Guardian, Student
from people.services import admit_student, correct_roll, transition_student, update_student

from .helpers import BACKEND, make_school_data, make_user


def image_upload(name="../../sensitive-name.jpg"):
    stream = io.BytesIO()
    Image.new("RGB", (40, 60), "blue").save(stream, format="JPEG", comment=b"private metadata")
    return SimpleUploadedFile(name, stream.getvalue(), content_type="image/jpeg")


class OperationsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.data = make_school_data()
        cls.next_year = AcademicYear.objects.create(
            name="2027-2028", starts_on=date(2027, 8, 1), ends_on=date(2028, 7, 31)
        )
        cls.grade = SchoolClass.objects.create(name="Grade 7", sort_order=7)
        cls.destination = Section.objects.create(school_class=cls.grade, name="A")

    def setUp(self):
        self.actor = self.data["admin"]
        self.client.force_login(self.actor, backend=BACKEND)

    def admission_data(self, **extra):
        return {
            "first_name": "New",
            "last_name": "Learner",
            "date_of_birth": date(2015, 1, 2),
            "admission_date": self.data["year"].starts_on,
            "external_reference": "source-101",
            **extra,
        }

    def admit(self, **extra):
        return admit_student(
            self.actor,
            data=self.admission_data(**extra),
            academic_year=self.data["year"],
            section=self.data["section"],
            started_on=self.data["year"].starts_on,
        )

    def transition(self, action="transfer", **extra):
        current = Enrollment.objects.get(student=self.data["own"], is_active=True)
        args = {
            "action": action,
            "effective_on": date(2026, 10, 1),
            "expected_enrollment": current.pk,
            **extra,
        }
        return transition_student(self.actor, self.data["own"].pk, **args)

    def csv_file(self, rows=None):
        row = {
            "external_reference": "source-101",
            "first_name": "New",
            "last_name": "Learner",
            "admission_date": "2026-08-01",
            "date_of_birth": "2015-01-02",
            "academic_year": str(self.data["year"].pk),
            "section": str(self.data["section"].pk),
            "started_on": "2026-08-01",
            "roll_number": "",
            "guardian": "",
            "relationship": "",
        }
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for item in rows or [row]:
            writer.writerow({**row, **item})
        return SimpleUploadedFile("admissions.csv", output.getvalue().encode())

    def test_auto_numbers_are_unique_and_audited(self):
        first = self.admit()
        second = self.admit(first_name="Another", external_reference="source-102")
        self.assertNotEqual(first.admission_number, second.admission_number)
        self.assertTrue(first.admission_number.startswith("RW-"))
        self.assertEqual(first.enrollments.count(), 1)
        self.assertTrue(
            AuditEvent.objects.filter(event="student.admitted", target=first.pk).exists()
        )

    def test_duplicate_identity_and_source_are_rejected(self):
        self.admit()
        for changes in (
            {},
            {"first_name": "Different", "external_reference": "SOURCE-101"},
            {"external_reference": "source-102"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.admit(**changes)
        self.assertEqual(Student.objects.count(), 4)

    def test_case_insensitive_admission_constraint(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Student.objects.create(
                first_name="Duplicate", last_name="Number", admission_number="test-001"
            )

    def test_blank_admission_constraint(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Student.objects.create(first_name="Blank", last_name="Number", admission_number="")

    def test_birth_date_constraint(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Student.objects.create(
                first_name="Invalid",
                last_name="Birth",
                admission_number="BAD-1",
                date_of_birth=date(2030, 1, 1),
            )

    def test_failed_admission_rolls_back_student_and_counter(self):
        before = Student.objects.count()
        with self.assertRaises(ValidationError):
            admit_student(
                self.actor,
                data=self.admission_data(),
                academic_year=self.data["year"],
                section=self.data["section"],
                started_on=date(2025, 1, 1),
            )
        self.assertEqual(Student.objects.count(), before)
        self.assertEqual(self.admit().admission_number, "RW-0000001")

    def test_transfer_keeps_previous_placement(self):
        self.transition(
            academic_year=self.data["year"], section=self.data["other_section"], roll_number="42"
        )
        active = Enrollment.objects.get(student=self.data["own"], is_active=True)
        self.assertEqual(active.started_on, date(2026, 10, 2))
        self.assertEqual(active.roll_number, "42")
        previous = Enrollment.objects.get(
            student=self.data["own"], academic_year=self.data["year"], is_active=False
        )
        self.assertEqual(previous.exit_reason, "transfer")
        self.assertEqual(previous.ended_on, date(2026, 10, 1))

    def test_stale_transition_rejected(self):
        self.transition(academic_year=self.data["year"], section=self.data["other_section"])
        with self.assertRaises(ValidationError):
            transition_student(
                self.actor,
                self.data["own"].pk,
                action="withdraw",
                effective_on=date(2026, 10, 2),
                expected_enrollment=0,
            )
        self.assertTrue(self.data["own"].enrollments.filter(is_active=True).exists())

    def test_transfer_same_section_and_out_of_year_rejected(self):
        for year, section in (
            (self.data["year"], self.data["section"]),
            (self.next_year, self.destination),
        ):
            with self.subTest(year=year), self.assertRaises(ValidationError):
                self.transition(academic_year=year, section=section)

    def test_transfer_at_year_end_rolls_back(self):
        with self.assertRaises(ValidationError):
            self.transition(
                academic_year=self.data["year"],
                section=self.data["other_section"],
                effective_on=self.data["year"].ends_on,
            )
        self.assertEqual(self.data["own"].enrollments.filter(is_active=True).count(), 1)

    def test_promotion_keeps_year_history(self):
        self.transition(
            "promote",
            academic_year=self.next_year,
            section=self.destination,
            effective_on=self.data["year"].ends_on,
        )
        active = self.data["own"].enrollments.get(is_active=True)
        self.assertEqual(active.academic_year, self.next_year)
        self.assertEqual(active.started_on, self.next_year.starts_on)
        self.assertEqual(self.data["own"].enrollments.count(), 3)

    def test_promotion_requires_later_year_and_higher_class(self):
        for year, section in (
            (self.data["year"], self.destination),
            (self.next_year, self.data["section"]),
        ):
            with self.subTest(year=year), self.assertRaises(ValidationError):
                self.transition("promote", academic_year=year, section=section)

    def test_exit_workflows_preserve_profile_and_history(self):
        for action, status in (
            ("withdraw", "withdrawn"),
            ("graduate", "graduated"),
            ("transfer_out", "transferred"),
        ):
            with self.subTest(action=action):
                student = self.admit(first_name=action, external_reference=action)
                current = student.enrollments.get(is_active=True)
                transition_student(
                    self.actor,
                    student.pk,
                    action=action,
                    effective_on=date(2026, 10, 1),
                    expected_enrollment=current.pk,
                )
                student.refresh_from_db()
                self.assertFalse(student.is_active)
                self.assertEqual(student.status, status)
                self.assertEqual(student.enrollments.count(), 1)
                with self.assertRaises(ValidationError):
                    update_student(self.actor, student.pk, {"first_name": "Rewrite"})

    def test_duplicate_active_across_years_rejected_by_database(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Enrollment.objects.create(
                student=self.data["own"],
                academic_year=self.next_year,
                section=self.destination,
                started_on=self.next_year.starts_on,
            )

    def test_overlap_rejected_by_database(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Enrollment.objects.create(
                student=self.data["own"],
                academic_year=self.data["year"],
                section=self.data["other_section"],
                started_on=date(2026, 9, 1),
                ended_on=date(2026, 9, 2),
                is_active=False,
            )

    def test_historical_rows_cannot_be_updated_or_deleted(self):
        historical = self.data["own"].enrollments.get(is_active=False)
        for operation in (
            lambda: Enrollment.objects.filter(pk=historical.pk).update(notes="Rewritten"),
            lambda: historical.delete(),
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                operation()

    def test_active_placement_identity_cannot_be_rewritten(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.data["own"].enrollments.filter(is_active=True).update(
                section=self.data["other_section"]
            )

    def test_active_roll_number_unique(self):
        admit_student(
            self.actor,
            data=self.admission_data(),
            academic_year=self.data["year"],
            section=self.data["section"],
            started_on=self.data["year"].starts_on,
            roll_number="R01",
        )
        with self.assertRaises(ValidationError):
            admit_student(
                self.actor,
                data=self.admission_data(first_name="Roll", external_reference="roll"),
                academic_year=self.data["year"],
                section=self.data["section"],
                started_on=self.data["year"].starts_on,
                roll_number="R01",
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Enrollment.objects.create(
                student=self.data["unassigned"],
                academic_year=self.data["year"],
                section=self.data["section"],
                started_on=self.data["year"].starts_on,
                roll_number="R01",
            )

    def test_authorized_active_roll_correction_retains_placement(self):
        current = self.data["own"].enrollments.get(is_active=True)
        result = correct_roll(
            self.actor, self.data["own"].pk, expected_enrollment=current.pk, roll_number="R12"
        )
        self.assertEqual(result.pk, current.pk)
        self.assertEqual(result.started_on, current.started_on)
        self.assertEqual(result.roll_number, "R12")
        self.assertTrue(AuditEvent.objects.filter(event="enrollment.roll_corrected").exists())
        with self.assertRaises(PermissionDenied):
            correct_roll(
                self.data["teacher_user"],
                self.data["own"].pk,
                expected_enrollment=current.pk,
                roll_number="R13",
            )
        with self.assertRaises(ValidationError):
            correct_roll(self.actor, self.data["own"].pk, expected_enrollment=0, roll_number="R13")

    def test_close_requires_resolved_enrollments_and_archiving_is_permanent(self):
        with self.assertRaises(ValidationError):
            period_action(self.actor, "years", self.data["year"].pk, "close")
        period_action(self.actor, "years", self.next_year.pk, "close")
        period_action(self.actor, "years", self.next_year.pk, "archive")
        with self.assertRaises(ValidationError):
            period_action(self.actor, "years", self.next_year.pk, "activate")

    def test_year_activation_and_term_lifecycle(self):
        period_action(self.actor, "years", self.next_year.pk, "activate")
        self.assertEqual(AcademicYear.objects.filter(is_current=True).get(), self.next_year)
        term = Term.objects.create(
            academic_year=self.next_year,
            name="Term 1",
            starts_on=self.next_year.starts_on,
            ends_on=self.next_year.ends_on,
        )
        period_action(self.actor, "terms", term.pk, "activate")
        self.assertTrue(Term.objects.get(pk=term.pk).is_current)
        period_action(self.actor, "years", self.next_year.pk, "close")
        self.assertEqual(Term.objects.get(pk=term.pk).status, "closed")
        self.assertFalse(Term.objects.get(pk=term.pk).is_current)

    def test_closed_year_rejects_admission_and_direct_enrollment(self):
        period_action(self.actor, "years", self.next_year.pk, "close")
        with self.assertRaises(ValidationError):
            admit_student(
                self.actor,
                data=self.admission_data(),
                academic_year=self.next_year,
                section=self.destination,
                started_on=self.next_year.starts_on,
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Enrollment.objects.create(
                student=self.data["unassigned"],
                academic_year=self.next_year,
                section=self.destination,
                started_on=self.next_year.starts_on,
            )

    def test_historical_academic_metadata_is_protected(self):
        form = ACADEMIC_FORMS["years"](
            {"name": "Rewritten", "starts_on": "2026-08-01", "ends_on": "2027-07-31"},
            instance=self.data["year"],
        )
        self.assertTrue(form.is_valid(), form.errors)
        with self.assertRaises(ValidationError):
            save_academic(self.actor, form)
        self.data["year"].refresh_from_db()
        self.assertNotEqual(self.data["year"].name, "Rewritten")

    def test_in_use_subject_and_section_definitions_are_protected(self):
        for kind, instance, values in (
            ("subjects", self.data["subject"], {"code": "RENAMED", "name": "Changed"}),
            (
                "sections",
                self.data["section"],
                {"school_class": self.data["section"].school_class_id, "name": "Changed"},
            ),
        ):
            with self.subTest(kind=kind):
                form = ACADEMIC_FORMS[kind](values, instance=instance)
                self.assertTrue(form.is_valid(), form.errors)
                with self.assertRaises(ValidationError):
                    save_academic(self.actor, form)

    def test_inactive_teacher_can_be_created_without_assignments(self):
        response = self.client.post(
            "/students/directory/teachers/new/",
            {
                "first_name": "Retired",
                "last_name": "Teacher",
                "employee_number": "RETIRED-1",
                "joined_on": "2025-08-01",
                "is_active": "",
            },
        )
        self.assertEqual(response.status_code, 302)

    def test_malformed_image_ids_and_numeric_filters_fail_closed(self):
        self.assertEqual(
            self.client.get("/students/images/students/invalid-uuid/").status_code, 404
        )
        for value in ("invalid", "²", "9" * 100):
            with self.subTest(value=value):
                response = self.client.get("/students/", {"year": value})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["page_obj"].paginator.count, 0)
                self.assertEqual(
                    self.client.get(
                        "/students/print/class/", {"year": value, "section": value}
                    ).status_code,
                    200,
                )

    def test_teaching_assignment_requires_class_subject(self):
        values = {
            "teacher": self.data["teacher"].pk,
            "academic_year": self.next_year.pk,
            "section": self.destination.pk,
            "subject": self.data["subject"].pk,
        }
        form = ACADEMIC_FORMS["assignments"](values)
        self.assertTrue(form.is_valid(), form.errors)
        with self.assertRaises(ValidationError):
            save_academic(self.actor, form)
        ClassSubject.objects.create(
            academic_year=self.next_year, school_class=self.grade, subject=self.data["subject"]
        )
        saved = save_academic(self.actor, form)
        self.assertEqual(saved.section, self.destination)

    def test_many_guardians_and_many_children(self):
        from people.directory_services import save_guardian_link

        other_guardian = Guardian.objects.create(first_name="Second", last_name="Guardian")
        for guardian, student in (
            (self.data["guardian"], self.data["other"]),
            (other_guardian, self.data["own"]),
        ):
            form = GuardianLinkForm(
                {"guardian": guardian.pk, "student": student.pk, "relationship": "Parent"}
            )
            self.assertTrue(form.is_valid(), form.errors)
            save_guardian_link(self.actor, form)
        self.assertEqual(self.data["own"].guardians.count(), 2)
        self.assertEqual(self.data["guardian"].students.count(), 2)

    def test_readers_cannot_write_even_their_own_record(self):
        urls = [
            "/students/admit/",
            "/students/import/",
            f"/students/{self.data['own'].pk}/edit/",
            f"/students/{self.data['own'].pk}/enrollment/",
            "/students/guardian-links/new/",
            "/academics/years/new/",
            "/students/directory/teachers/new/",
        ]
        for key in ("student_user", "teacher_user", "parent", "accountant"):
            self.client.force_login(self.data[key], backend=BACKEND)
            for url in urls:
                for method in (self.client.get, self.client.post):
                    with self.subTest(role=key, url=url, method=method.__name__):
                        self.assertEqual(method(url, {}).status_code, 403)

    def test_custom_write_permission_without_global_scope_denied(self):
        user = self.data["teacher_user"]
        user.user_permissions.add(Permission.objects.get(codename="change_student"))
        self.client.force_login(user, backend=BACKEND)
        self.assertEqual(
            self.client.post(
                f"/students/{self.data['own'].pk}/edit/", {"first_name": "Hacked"}
            ).status_code,
            403,
        )
        with self.assertRaises(PermissionDenied):
            update_student(user, self.data["own"].pk, {"first_name": "Hacked"})

    def test_service_layer_permissions(self):
        for actor in (
            self.data["student_user"],
            self.data["parent"],
            self.data["teacher_user"],
            self.data["accountant"],
        ):
            with self.subTest(actor=actor.pk), self.assertRaises(PermissionDenied):
                admit_student(
                    actor,
                    data=self.admission_data(),
                    academic_year=self.data["year"],
                    section=self.data["section"],
                    started_on=self.data["year"].starts_on,
                )

    def test_hr_can_manage_staff_but_not_admissions(self):
        user = make_user("hrmanager", "HR Manager")
        self.client.force_login(user, backend=BACKEND)
        self.assertEqual(self.client.get("/students/directory/staff/new/").status_code, 200)
        self.assertEqual(self.client.get("/students/admit/").status_code, 403)

    def test_csrf_enforced_on_admission(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.actor, backend=BACKEND)
        self.assertEqual(client.post("/students/admit/", {}).status_code, 403)

    def test_pages_and_validation_render(self):
        urls = [
            "/students/admit/",
            "/students/import/",
            "/students/guardian-links/new/",
            "/students/directory/guardians/",
            "/students/directory/teachers/",
            "/students/directory/staff/",
            f"/students/directory/teachers/{self.data['teacher'].pk}/",
            f"/students/directory/guardians/{self.data['guardian'].pk}/",
            f"/students/{self.data['own'].pk}/edit/",
            f"/students/{self.data['own'].pk}/enrollment/",
        ]
        for kind in ACADEMIC_FORMS:
            urls += [f"/academics/{kind}/", f"/academics/{kind}/new/"]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        self.assertContains(self.client.post("/students/admit/", {}), "This field is required")

    def test_admission_http_flow_and_protected_fields(self):
        values = {
            **self.admission_data(),
            "academic_year": self.data["year"].pk,
            "section": self.data["section"].pk,
            "started_on": "2026-08-01",
            "admission_number": "FORGED",
            "is_active": False,
        }
        response = self.client.post("/students/admit/", values)
        self.assertEqual(response.status_code, 302)
        student = Student.objects.get(external_reference="source-101")
        self.assertNotEqual(student.admission_number, "FORGED")
        self.assertTrue(student.is_active)

    def test_scoped_prints_and_filters_do_not_leak_history(self):
        self.client.force_login(self.data["teacher_user"], backend=BACKEND)
        response = self.client.get(f"/students/{self.data['own'].pk}/print/profile/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.data["old_year"].name)
        self.assertNotContains(response, "Fictional Guardian")
        self.assertEqual(
            self.client.get(f"/students/{self.data['other'].pk}/print/admission/").status_code, 404
        )
        response = self.client.get(
            "/students/print/class/",
            {"year": self.data["year"].pk, "section": self.data["other_section"].pk},
        )
        self.assertNotContains(response, "TEST-002")
        response = self.client.get(
            "/students/", {"year": self.data["old_year"].pk, "sort": "admission"}
        )
        self.assertNotContains(response, "TEST-001")

    def test_csv_preview_has_no_admissions_and_confirm_is_single_use(self):
        count = Student.objects.count()
        results, batch = preview_import(self.actor, self.csv_file())
        self.assertFalse(results[0]["errors"])
        self.assertIsNotNone(batch)
        self.assertEqual(Student.objects.count(), count)
        self.assertEqual(confirm_import(self.actor, batch.pk), 1)
        batch.refresh_from_db()
        self.assertEqual(batch.rows, [])
        with self.assertRaises(ValidationError):
            confirm_import(self.actor, batch.pk)

    def test_csv_duplicate_in_file_or_database(self):
        for rows in ([{}, {}], [{}, {"first_name": "Other", "external_reference": "SOURCE-101"}]):
            results, batch = preview_import(self.actor, self.csv_file(rows))
            self.assertIsNone(batch)
            self.assertTrue(results[1]["errors"])
        self.admit()
        results, batch = preview_import(self.actor, self.csv_file())
        self.assertIsNone(batch)
        self.assertTrue(results[0]["errors"])

    def test_csv_invalid_foreign_keys_dates_and_references(self):
        for row in (
            {"academic_year": "999999"},
            {"section": "999999"},
            {"date_of_birth": "wrong"},
            {"external_reference": ""},
            {"started_on": "2026-07-31"},
            {"guardian": self.data["guardian"].pk, "relationship": ""},
        ):
            with self.subTest(row=row):
                results, batch = preview_import(self.actor, self.csv_file([row]))
                self.assertIsNone(batch)
                self.assertTrue(results[0]["errors"])

    def test_csv_size_headers_encoding_and_row_limits(self):
        for raw in (
            b"x" * (1024 * 1024 + 1),
            b"a,a\nx,y",
            b"\xff",
            b"",
            b"unexpected\nvalue",
            b"first_name\x00\nx",
        ):
            with self.subTest(raw=raw[:20]), self.assertRaises(ValidationError):
                preview_import(self.actor, SimpleUploadedFile("bad.csv", raw))
        with self.assertRaises(ValidationError):
            preview_import(self.actor, self.csv_file([{}] * 501))

    def test_csv_confirmation_revalidates_and_rolls_back_all_rows(self):
        _, batch = preview_import(
            self.actor,
            self.csv_file([{}, {"first_name": "Second", "external_reference": "source-102"}]),
        )
        self.admit(first_name="Different", external_reference="source-102")
        count = Student.objects.count()
        with self.assertRaises(ValidationError):
            confirm_import(self.actor, batch.pk)
        self.assertEqual(Student.objects.count(), count)
        self.assertFalse(Student.objects.filter(external_reference="source-101").exists())

    def test_csv_failure_during_second_write_rolls_back_first(self):
        _, batch = preview_import(
            self.actor,
            self.csv_file([{}, {"first_name": "Second", "external_reference": "source-102"}]),
        )
        count = Student.objects.count()
        calls = []

        def fail_second(*args, **kwargs):
            calls.append(True)
            if len(calls) == 2:
                raise ValidationError("Injected failure")
            return admit_student(*args, **kwargs)

        with (
            patch("people.imports.admit_student", side_effect=fail_second),
            self.assertRaises(ValidationError),
        ):
            confirm_import(self.actor, batch.pk)
        self.assertEqual(Student.objects.count(), count)
        self.assertIsNone(AdmissionImport.objects.get(pk=batch.pk).confirmed_at)

    def test_csv_owner_expiry_and_permission_revocation(self):
        _, batch = preview_import(self.actor, self.csv_file())
        other = make_user("secondadmin", "School Administrator")
        with self.assertRaises(PermissionDenied):
            confirm_import(other, batch.pk)
        self.client.force_login(other, backend=BACKEND)
        self.assertEqual(
            self.client.get(reverse("people:import_confirm", args=[batch.pk])).status_code, 404
        )
        batch.expires_at = timezone.now() - timedelta(seconds=1)
        batch.save()
        with self.assertRaises(ValidationError):
            confirm_import(self.actor, batch.pk)
        self.actor.groups.clear()
        self.actor = type(self.actor).objects.get(pk=self.actor.pk)
        with self.assertRaises(PermissionDenied):
            confirm_import(self.actor, batch.pk)

    def test_csv_http_requires_confirmation(self):
        response = self.client.post("/students/import/", {"file": self.csv_file()})
        self.assertContains(response, "Continue to confirmation")
        batch = AdmissionImport.objects.get()
        self.assertContains(
            self.client.post(reverse("people:import_confirm", args=[batch.pk]), {}),
            "This field is required",
        )
        self.assertIsNone(AdmissionImport.objects.get(pk=batch.pk).confirmed_at)
        self.assertEqual(
            self.client.post(
                reverse("people:import_confirm", args=[batch.pk]), {"confirm": "on"}
            ).status_code,
            302,
        )

    def test_images_reencoded_with_random_names_and_bounded_content(self):
        result = sanitize_image(image_upload())
        self.assertTrue(result.name.endswith(".png"))
        self.assertNotIn("sensitive", result.name)
        image = Image.open(result)
        self.assertEqual(image.format, "PNG")
        self.assertNotIn("comment", image.info)
        for upload in (
            SimpleUploadedFile("evil.svg", b"<svg onload='alert(1)'/>"),
            SimpleUploadedFile("huge.jpg", b"x" * (2 * 1024 * 1024 + 1)),
            SimpleUploadedFile("fake.jpg", b"not an image"),
        ):
            with self.assertRaises(ValidationError):
                sanitize_image(upload)

    def test_private_image_route_enforces_object_scope(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            override_settings(
                STORAGES={
                    "default": {
                        "BACKEND": "django.core.files.storage.FileSystemStorage",
                        "OPTIONS": {"location": directory},
                    },
                    "staticfiles": {
                        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
                    },
                }
            ),
        ):
            response = self.client.post(
                f"/students/{self.data['other'].pk}/edit/",
                {"first_name": "Other", "last_name": "Learner", "photo": image_upload()},
            )
            self.assertEqual(response.status_code, 302)
            url = reverse("people:image", args=["students", self.data["other"].pk])
            saved = Student.objects.get(pk=self.data["other"].pk)
            edit = self.client.get(f"/students/{saved.pk}/edit/")
            self.assertContains(edit, "An image is saved")
            self.assertNotContains(edit, saved.photo.name)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertIn("private", response["Cache-Control"])
            self.assertTrue(b"".join(response.streaming_content).startswith(b"\x89PNG"))
            self.client.force_login(self.data["student_user"], backend=BACKEND)
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_school_branding_and_unsafe_logo_validation(self):
        response = self.client.post(
            "/settings/school/",
            {
                "name": "School",
                "timezone": "Asia/Karachi",
                "currency": "PKR",
                "logo": SimpleUploadedFile("bad.svg", b"<svg/>"),
                "email": "invalid",
            },
        )
        self.assertContains(response, "valid email")
        self.assertContains(response, "valid PNG or JPEG")

    def test_failed_admission_removes_new_image_file(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            override_settings(
                STORAGES={
                    "default": {
                        "BACKEND": "django.core.files.storage.FileSystemStorage",
                        "OPTIONS": {"location": directory},
                    },
                    "staticfiles": {
                        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
                    },
                }
            ),
        ):
            with self.assertRaises(ValidationError):
                admit_student(
                    self.actor,
                    data=self.admission_data(photo=sanitize_image(image_upload())),
                    academic_year=self.data["year"],
                    section=self.data["section"],
                    started_on=date(2027, 8, 1),
                )
            self.assertEqual([p for p in Path(directory).rglob("*") if p.is_file()], [])

    def test_expired_csv_personal_data_can_be_purged(self):
        _, batch = preview_import(self.actor, self.csv_file())
        batch.expires_at = timezone.now() - timedelta(minutes=1)
        batch.save()
        call_command("purge_admission_previews", stdout=io.StringIO())
        batch.refresh_from_db()
        self.assertEqual(batch.rows, [])
        self.assertIsNone(batch.confirmed_at)
