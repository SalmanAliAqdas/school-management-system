from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connections
from django.test import TransactionTestCase

from people.models import Enrollment, Student
from people.services import admit_student, transition_student

from .helpers import make_school_data


class EnrollmentConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.data = make_school_data()

    def run_workers(self, operation):
        barrier = Barrier(2)

        def worker(index):
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=self.data["admin"].pk)
                barrier.wait(timeout=10)
                return operation(actor, index)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(worker, i) for i in range(2)]
            return [future.result(timeout=30) for future in futures]

    def test_simultaneous_admissions_have_distinct_numbers(self):
        def operation(actor, index):
            student = admit_student(
                actor,
                data={
                    "first_name": f"Concurrent {index}",
                    "last_name": "Learner",
                    "admission_date": date(2026, 8, 1),
                    "date_of_birth": date(2015, 1, 2),
                    "external_reference": f"concurrent-{index}",
                },
                academic_year=self.data["year"],
                section=self.data["section"],
                started_on=date(2026, 8, 1),
            )
            return student.admission_number

        results = self.run_workers(operation)
        self.assertEqual(len(set(results)), 2)

    def test_simultaneous_duplicate_admission_creates_one_student(self):
        def operation(actor, index):
            try:
                admit_student(
                    actor,
                    data={
                        "first_name": "Same",
                        "last_name": "Learner",
                        "admission_date": date(2026, 8, 1),
                        "date_of_birth": date(2015, 1, 2),
                        "external_reference": "same-source",
                    },
                    academic_year=self.data["year"],
                    section=self.data["section"],
                    started_on=date(2026, 8, 1),
                )
                return "saved"
            except ValidationError:
                return "rejected"

        self.assertCountEqual(self.run_workers(operation), ["saved", "rejected"])
        self.assertEqual(Student.objects.filter(external_reference="same-source").count(), 1)

    def test_simultaneous_transfers_cannot_create_two_active_placements(self):
        current = Enrollment.objects.get(student=self.data["own"], is_active=True)

        def operation(actor, index):
            try:
                transition_student(
                    actor,
                    self.data["own"].pk,
                    action="transfer",
                    effective_on=date(2026, 10, 1),
                    expected_enrollment=current.pk,
                    academic_year=self.data["year"],
                    section=self.data["other_section"],
                )
                return "saved"
            except ValidationError:
                return "rejected"

        self.assertCountEqual(self.run_workers(operation), ["saved", "rejected"])
        self.assertEqual(self.data["own"].enrollments.filter(is_active=True).count(), 1)
