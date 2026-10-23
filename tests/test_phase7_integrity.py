from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
from threading import Barrier

from django.core.exceptions import ValidationError
from django.db import DatabaseError, connections, transaction
from django.test import TransactionTestCase

from attendance.models import AttendancePolicy, CalendarEvent
from attendance.services import decide_leave, request_leave
from communications import services as comm
from communications.models import CommunicationPolicy, Message
from learning import services as learn
from learning.models import SubmissionVersion
from scheduling import services as schedule
from scheduling.models import Booking, Entry, Timetable
from tests.test_phase7 import Phase7Fixture


class DatabaseGuardTests(Phase7Fixture):
    def test_approved_leave_conflicts(self):
        leave = request_leave(
            self.teacher,
            year_id=self.d["year"].pk,
            person=self.d["teacher"],
            starts_on=date(2026, 10, 26),
            ends_on=date(2026, 10, 26),
            kind="casual",
            reason="Appointment",
        )
        decide_leave(self.admin, leave.pk, approve=True)
        with self.assertRaisesMessage(ValidationError, "leave"):
            schedule.save_entry(self.admin, self.entry, 1)

    def test_closure_omits_occurrence(self):
        AttendancePolicy.objects.create(
            academic_year=self.d["year"], effective_from=self.d["year"].starts_on
        )
        CalendarEvent.objects.create(
            academic_year=self.d["year"],
            title="School closure",
            created_by=self.admin,
            starts_on=date(2026, 10, 26),
            ends_on=date(2026, 10, 26),
            kind="closure",
        )
        schedule.save_entry(self.admin, self.entry, 1)
        schedule.transition(self.admin, self.table.pk, "publish")
        self.assertEqual(Booking.objects.count(), 1)
        self.assertEqual(Booking.objects.get().date, date(2026, 11, 2))

    def test_database_rejects_resource_collision(self):
        schedule.save_entry(self.admin, self.entry, 1)
        schedule.transition(self.admin, self.table.pk, "publish")
        booking = Booking.objects.first()
        with self.assertRaises(DatabaseError), transaction.atomic():
            Booking.objects.create(
                entry=self.entry,
                date=booking.date + timedelta(days=1),
                starts_at=booking.starts_at,
                ends_at=booking.ends_at,
                teacher=booking.teacher,
                section=booking.section,
                room=booking.room,
            )

    def test_published_entry_direct_update_rejected(self):
        schedule.save_entry(self.admin, self.entry, 1)
        schedule.transition(self.admin, self.table.pk, "publish")
        with self.assertRaises(DatabaseError), transaction.atomic():
            Entry.objects.filter(pk=self.entry.pk).update(room=self.room)

    def test_submission_version_direct_update_rejected(self):
        row = self.submitted()
        with self.assertRaises(DatabaseError), transaction.atomic():
            row.versions.update(text="Tampered")

    def test_feedback_direct_update_rejected(self):
        row = self.submitted()
        feedback = learn.review(
            self.teacher, row.pk, text="Initial", outcome="graded", marks=Decimal(70)
        )
        with self.assertRaises(DatabaseError), transaction.atomic():
            type(feedback).objects.filter(pk=feedback.pk).update(marks=99)

    def test_message_content_cannot_be_rewritten(self):
        row = comm.send(
            self.parent,
            "Original",
            recipient=self.teacher,
            student=self.d["own"],
            subject="Progress",
        )
        with self.assertRaises(DatabaseError), transaction.atomic():
            row.messages.update(body="Rewritten")

    def test_message_read_state_remains_mutable(self):
        from django.utils import timezone

        row = comm.send(
            self.parent,
            "Original",
            recipient=self.teacher,
            student=self.d["own"],
            subject="Progress",
        )
        row.messages.update(read_at=timezone.now())
        self.assertIsNotNone(row.messages.get().read_at)

    def test_excused_not_missing(self):
        from learning.reporting import assignment_report

        self.assignment.due_at -= timedelta(days=3)
        self.assignment.publish_at -= timedelta(days=4)
        self.homework()
        learn.excuse(self.teacher, self.assignment.pk, self.d["own"].pk, "Approved exemption")
        report = assignment_report(self.teacher, self.assignment)
        self.assertEqual(report["excused"], 1)
        self.assertEqual(report["missing"], 0)

    def test_rubric_validation_and_scoring(self):
        self.assignment.rubric = {"Reasoning": 60, "Presentation": 40}
        row = self.submitted()
        with self.assertRaises(ValidationError):
            learn.review(
                self.teacher,
                row.pk,
                text="Review",
                outcome="graded",
                marks=Decimal(80),
                criterion_marks={"Reasoning": 80, "Presentation": 0},
            )
        feedback = learn.review(
            self.teacher,
            row.pk,
            text="Review",
            outcome="graded",
            marks=Decimal(80),
            criterion_marks={"Reasoning": 50, "Presentation": 30},
        )
        self.assertEqual(feedback.marks, 80)


class ConcurrentWritesTests(TransactionTestCase):
    setUp = Phase7Fixture.setUp
    homework = Phase7Fixture.homework

    def concurrent(self, first, second):
        barrier = Barrier(2)

        def worker(callback):
            try:
                barrier.wait(timeout=15)
                callback()
                return "saved"
            except ValidationError:
                return "rejected"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(worker, first)
            b = pool.submit(worker, second)
            return sorted([a.result(timeout=45), b.result(timeout=45)])

    def test_two_publishers_cannot_double_book(self):
        schedule.save_entry(self.admin, self.entry, 1)
        second = Timetable.objects.create(
            title="Competing draft",
            academic_year=self.table.academic_year,
            starts_on=self.table.starts_on,
            ends_on=self.table.ends_on,
        )
        schedule.save_entry(
            self.admin,
            Entry(timetable=second, period=self.period, assignment=self.teaching, room=self.room),
            1,
        )
        result = self.concurrent(
            lambda: schedule.transition(self.admin, self.table.pk, "publish"),
            lambda: schedule.transition(self.admin, second.pk, "publish"),
        )
        self.assertEqual(result, ["rejected", "saved"])
        self.assertEqual(Timetable.objects.filter(state="published").count(), 1)

    def test_two_final_submissions_create_one_version(self):
        self.homework()
        result = self.concurrent(
            lambda: learn.submit(self.student, self.assignment.pk, "First", final=True),
            lambda: learn.submit(self.student, self.assignment.pk, "Second", final=True),
        )
        self.assertEqual(result, ["rejected", "saved"])
        self.assertEqual(SubmissionVersion.objects.count(), 1)

    def test_concurrent_message_rate_limit(self):
        CommunicationPolicy.objects.create(messages_per_hour=1)
        result = self.concurrent(
            lambda: comm.send(
                self.parent, "First", recipient=self.teacher, student=self.d["own"], subject="First"
            ),
            lambda: comm.send(
                self.parent,
                "Second",
                recipient=self.teacher,
                student=self.d["own"],
                subject="Second",
            ),
        )
        self.assertEqual(result, ["rejected", "saved"])
        self.assertEqual(Message.objects.count(), 1)


class RevocationAndSubstitutionTests(Phase7Fixture):
    def test_revoked_assignment_removes_all_current_teacher_scopes(self):
        from communications.selectors import conversations
        from learning.selectors import visible
        from portals.selectors import assignments

        self.homework()
        comm.send(
            self.parent, "Hello", recipient=self.teacher, student=self.d["own"], subject="Progress"
        )
        schedule.assignment_access(
            self.admin, self.teaching.pk, False, "Reassigned teaching responsibility"
        )
        self.assertFalse(assignments(self.teacher).exists())
        self.assertFalse(visible(self.teacher).exists())
        self.assertFalse(conversations(self.teacher).exists())
        from academics.models import TeachingAssignment

        self.assertTrue(
            TeachingAssignment.all_objects.filter(pk=self.teaching.pk, is_active=False).exists()
        )
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.title, "Explore fractions")

    def test_substitution_roster_is_only_available_on_approved_date(self):
        from unittest.mock import patch

        from academics.models import TeachingAssignment
        from people.models import Teacher
        from tests.helpers import make_user
        from tests.test_phase7 import NOW

        user = make_user("substitute", "Teacher")
        teacher = Teacher.objects.create(
            user=user,
            first_name="Cover",
            last_name="Teacher",
            employee_number="COVER",
            joined_on=self.d["year"].starts_on,
        )
        TeachingAssignment.objects.create(
            teacher=teacher,
            academic_year=self.d["year"],
            section=self.d["other_section"],
            subject=self.d["subject"],
        )
        schedule.save_entry(self.admin, self.entry, 1)
        schedule.transition(self.admin, self.table.pk, "publish")
        duty = schedule.substitute(
            self.admin, self.entry.pk, date(2026, 10, 26), teacher, "Cover lesson", approve=True
        )
        self.login(user)
        self.assertEqual(self.client.get(f"/scheduling/duties/{duty.pk}/").status_code, 404)
        with patch("django.utils.timezone.now", return_value=NOW + timedelta(days=3)):
            self.login(user)
            response = self.client.get(f"/scheduling/duties/{duty.pk}/")
            self.assertContains(response, "Fictional Learner")
            self.assertNotContains(response, "TEST-002")
            self.assertEqual(
                self.client.get(f"/portals/teacher/classes/{self.teaching.pk}/").status_code, 404
            )

    def test_self_substitution_rejected(self):
        schedule.save_entry(self.admin, self.entry, 1)
        schedule.transition(self.admin, self.table.pk, "publish")
        with self.assertRaises(ValidationError):
            schedule.substitute(
                self.admin, self.entry.pk, date(2026, 10, 26), self.d["teacher"], "No"
            )

    def test_private_message_attachment_revoked_with_relationship(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from communications.models import Document

        row = comm.send(
            self.parent,
            "Attached",
            recipient=self.teacher,
            student=self.d["own"],
            subject="Attachment",
            files=[SimpleUploadedFile("note.txt", b"Family note", content_type="text/plain")],
        )
        doc = Document.objects.get(message__conversation=row)
        self.login(self.teacher)
        self.assertEqual(self.client.get(f"/communications/documents/{doc.pk}/").status_code, 200)
        self.d["guardian"].student_links.all().delete()
        self.assertEqual(self.client.get(f"/communications/documents/{doc.pk}/").status_code, 404)

    def test_unrelated_section_announcement_is_hidden(self):
        from communications.selectors import publications

        row = self.publication(academic_year=self.d["year"], section=self.d["other_section"])
        CommunicationPolicy.objects.create(require_approval=False)
        comm.publication_action(self.admin, row.pk, "publish")
        self.assertFalse(publications(self.parent).exists())

    def test_material_deadline_change_keeps_history(self):
        from learning.models import AssignmentChange

        self.homework()
        self.assignment.refresh_from_db()
        self.assignment.due_at += timedelta(days=1)
        learn.save_assignment(self.teacher, self.assignment, self.assignment.revision)
        self.assertEqual(AssignmentChange.objects.filter(assignment=self.assignment).count(), 3)

    def test_expired_announcement_is_hidden(self):
        from communications.selectors import publications
        from tests.test_phase7 import NOW

        row = self.publication(
            kind="announcement",
            publish_at=NOW - timedelta(days=2),
            expires_at=NOW - timedelta(days=1),
        )
        CommunicationPolicy.objects.create(require_approval=False)
        comm.publication_action(self.admin, row.pk, "publish")
        self.assertFalse(publications(self.student).exists())
