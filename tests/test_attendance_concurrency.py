from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connections
from django.test import TransactionTestCase

from attendance.models import (
    AbsenceNotification,
    AttendancePolicy,
    StudentAttendance,
    StudentRegister,
)
from attendance.services import decide_correction, request_correction, save_student_register

from .helpers import make_school_data, make_user


class AttendanceConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.data = make_school_data()
        self.reviewer = make_user("attendanceconcurrentreview", "Principal")
        self.second = make_user("attendanceconcurrentreview2", "Principal")
        self.day = date(2026, 10, 5)
        AttendancePolicy.objects.create(
            academic_year=self.data["year"], effective_from=self.data["year"].starts_on
        )
        self.enrollment = self.data["own"].enrollments.get(is_active=True)

    def concurrent(self, operation):
        barrier = Barrier(2)

        def worker(index):
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=[self.reviewer.pk, self.second.pk][index])
                barrier.wait(timeout=10)
                try:
                    operation(actor)
                    return "saved"
                except ValidationError:
                    return "rejected"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(worker, index) for index in range(2)]
            return [job.result(timeout=30) for job in jobs]

    def create(self, actor):
        return save_student_register(
            actor,
            year_id=self.data["year"].pk,
            section_id=self.data["section"].pk,
            day=self.day,
            rows={str(self.enrollment.pk): {"status": "absent"}},
            final=True,
            reason="Concurrent fictional register test",
        )

    def test_simultaneous_finalization_creates_one_register_and_notification(self):
        self.assertCountEqual(self.concurrent(self.create), ["saved", "rejected"])
        self.assertEqual(StudentRegister.objects.count(), 1)
        self.assertEqual(StudentAttendance.objects.count(), 1)
        self.assertEqual(AbsenceNotification.objects.count(), 1)

    def test_simultaneous_correction_decisions_apply_once(self):
        entry = self.create(self.data["admin"]).entries.get()
        correction = request_correction(
            self.data["admin"],
            kind="student",
            entry_id=entry.pk,
            values={"status": "present"},
            reason="Concurrent correction review",
        )
        self.assertCountEqual(
            self.concurrent(lambda actor: decide_correction(actor, correction.pk, approve=True)),
            ["saved", "rejected"],
        )
        entry.refresh_from_db()
        self.assertEqual(entry.revision, 1)
        self.assertEqual(entry.status, "present")
