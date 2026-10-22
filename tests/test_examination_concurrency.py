from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connections
from django.test import TransactionTestCase

from examinations.models import MarkEntry, MarkSheet, ResultPublication
from examinations.services import decide_correction, request_correction, save_marks, session_action

from .helpers import make_user
from .test_examinations import ExaminationFixture


class ExaminationConcurrencyTests(ExaminationFixture, TransactionTestCase):
    def setUp(self):
        type(self).setUpTestData()
        self.second = make_user("secondexamprincipal", "Principal")
        self.open()

    def race(self, callback):
        barrier = Barrier(2)

        def run(index):
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=[self.principal.pk, self.second.pk][index])
                barrier.wait(timeout=10)
                try:
                    callback(actor)
                    return "saved"
                except ValidationError:
                    return "rejected"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(run, index) for index in range(2)]
            return [job.result(timeout=30) for job in jobs]

    def test_simultaneous_marks_submission_has_one_winner(self):
        rows = {str(self.candidate.pk): {"status": "assessed", "marks": "81", "remarks": ""}}
        self.assertCountEqual(
            self.race(
                lambda actor: save_marks(
                    actor, self.sheet.pk, rows, expected_version=0, submit=True
                )
            ),
            ["saved", "rejected"],
        )
        self.assertEqual(MarkEntry.objects.count(), 1)
        self.assertEqual(MarkSheet.objects.get(pk=self.sheet.pk).version, 1)

    def test_simultaneous_publication_creates_one_version(self):
        self.mark()
        self.approve_sheet()
        self.action("close")
        self.action("review", self.controller)
        self.action("approve", self.principal)
        version = self.session.version
        self.assertCountEqual(
            self.race(
                lambda actor: session_action(
                    actor,
                    self.session.pk,
                    "publish",
                    expected_version=version,
                    reason="Concurrent publication test",
                )
            ),
            ["saved", "rejected"],
        )
        self.assertEqual(ResultPublication.objects.count(), 1)

    def test_simultaneous_correction_decisions_apply_and_publish_once(self):
        self.mark()
        self.approve_sheet()
        self.action("close")
        self.action("review", self.controller)
        self.action("approve", self.principal)
        self.action("publish")
        entry = MarkEntry.objects.get(candidate=self.candidate)
        request = request_correction(
            self.teacher,
            entry.pk,
            status="assessed",
            marks="90",
            remarks="Rechecked",
            reason="Concurrent correction example",
        )
        self.assertCountEqual(
            self.race(
                lambda actor: decide_correction(
                    actor, request.pk, approve=True, reason="Independent concurrent review"
                )
            ),
            ["saved", "rejected"],
        )
        entry.refresh_from_db()
        self.assertEqual(entry.marks, 90)
        self.assertEqual(entry.version, 1)
        self.assertEqual(ResultPublication.objects.count(), 2)
