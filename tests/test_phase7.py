from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase

from academics.models import TeachingAssignment
from communications import selectors as cs
from communications import services as comm
from communications.models import CommunicationPolicy, Message, Notice, Publication
from communications.notices import visible as notices
from learning import selectors as ls
from learning import services as learn
from learning.models import Assignment, Attachment, SubmissionVersion
from learning.uploads import read_private_upload
from people.models import Teacher
from scheduling import selectors as ss
from scheduling import services as schedule
from scheduling.models import Availability, Entry, Period, Room, Timetable
from tests.helpers import BACKEND, make_school_data, make_user

NOW = datetime(2026, 10, 23, 10, tzinfo=ZoneInfo("Asia/Karachi"))


class Phase7Fixture(TestCase):
    def setUp(self):
        self.clock = patch("django.utils.timezone.now", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.d = make_school_data()
        self.d["teacher"].joined_on = date(2026, 8, 1)
        self.d["teacher"].save()
        self.teaching = TeachingAssignment.objects.get(teacher=self.d["teacher"])
        self.room = Room.objects.create(name="Learning room")
        self.period = Period.objects.create(
            academic_year=self.d["year"],
            name="First",
            weekday=0,
            starts_at=time(8),
            ends_at=time(8, 40),
        )
        self.table = Timetable.objects.create(
            title="Autumn week",
            academic_year=self.d["year"],
            starts_on=date(2026, 10, 26),
            ends_on=date(2026, 11, 6),
        )
        self.entry = Entry(
            timetable=self.table, period=self.period, assignment=self.teaching, room=self.room
        )
        self.assignment = Assignment(
            teaching=self.teaching,
            title="Explore fractions",
            description="Explain your reasoning.",
            publish_at=NOW - timedelta(hours=1),
            due_at=NOW + timedelta(days=2),
            maximum=100,
        )
        self.admin = self.d["admin"]
        self.teacher = self.d["teacher_user"]
        self.student = self.d["student_user"]
        self.parent = self.d["parent"]

    def homework(self):
        learn.save_assignment(self.teacher, self.assignment)
        return learn.transition(self.teacher, self.assignment.pk, "publish")

    def submitted(self):
        self.homework()
        return learn.submit(self.student, self.assignment.pk, "My reasoning", final=True)

    def publication(self, **kwargs):
        values = dict(
            kind="event",
            title="Family learning evening",
            body="Join the school community.",
            publish_at=NOW - timedelta(hours=1),
            starts_at=NOW + timedelta(days=2),
            ends_at=NOW + timedelta(days=2, hours=1),
            author=self.admin,
        )
        values.update(kwargs)
        return comm.save_publication(self.admin, Publication(**values))

    def login(self, user):
        self.client.force_login(user, backend=BACKEND)


class TimetableTests(Phase7Fixture):
    def test_period_time_order(self):
        self.period.ends_at = time(7)
        with self.assertRaises(ValidationError):
            schedule.save_setup(self.admin, self.period)

    def test_draft_hidden_from_families(self):
        schedule.save_entry(self.admin, self.entry, 1)
        self.assertFalse(ss.tables(self.student).exists())
        self.assertFalse(ss.tables(self.parent).exists())

    def test_publish_visible_to_current_cohort(self):
        schedule.save_entry(self.admin, self.entry, 1)
        schedule.transition(self.admin, self.table.pk, "publish")
        self.assertEqual(ss.tables(self.student).get(), self.table)
        self.assertTrue(ss.tables(self.teacher).exists())

    def test_teacher_cannot_edit_timetable(self):
        with self.assertRaises(PermissionDenied):
            schedule.save_entry(self.teacher, self.entry, 1)

    def test_teacher_overlap_rejected(self):
        schedule.save_entry(self.admin, self.entry, 1)
        second = TeachingAssignment.objects.create(
            teacher=self.d["teacher"],
            academic_year=self.d["year"],
            section=self.d["other_section"],
            subject=self.d["subject"],
        )
        row = Entry(
            timetable=self.table,
            period=self.period,
            assignment=second,
            room=Room.objects.create(name="Other"),
        )
        with self.assertRaisesMessage(ValidationError, "Teacher conflict"):
            schedule.save_entry(self.admin, row, 2)

    def test_room_overlap_rejected(self):
        schedule.save_entry(self.admin, self.entry, 1)
        teacher = Teacher.objects.create(
            first_name="Other",
            last_name="Teacher",
            employee_number="T2",
            joined_on=date(2026, 8, 1),
        )
        assigned = TeachingAssignment.objects.create(
            teacher=teacher,
            academic_year=self.d["year"],
            section=self.d["other_section"],
            subject=self.d["subject"],
        )
        row = Entry(timetable=self.table, period=self.period, assignment=assigned, room=self.room)
        with self.assertRaisesMessage(ValidationError, "Room"):
            schedule.save_entry(self.admin, row, 2)

    def test_section_overlap_rejected(self):
        schedule.save_entry(self.admin, self.entry, 1)
        teacher = Teacher.objects.create(
            first_name="Other",
            last_name="Teacher",
            employee_number="T2",
            joined_on=date(2026, 8, 1),
        )
        assigned = TeachingAssignment.objects.create(
            teacher=teacher,
            academic_year=self.d["year"],
            section=self.d["section"],
            subject=self.d["subject"],
        )
        row = Entry(
            timetable=self.table,
            period=self.period,
            assignment=assigned,
            room=Room.objects.create(name="Other"),
        )
        with self.assertRaisesMessage(ValidationError, "Section"):
            schedule.save_entry(self.admin, row, 2)

    def test_stale_edit_rejected(self):
        schedule.save_entry(self.admin, self.entry, 1)
        with self.assertRaisesMessage(ValidationError, "Reload"):
            schedule.save_entry(self.admin, self.entry, 1)

    def test_year_mismatch_rejected(self):
        self.period.academic_year = self.d["old_year"]
        self.period.save()
        with self.assertRaises(ValidationError):
            schedule.save_entry(self.admin, self.entry, 1)

    def test_employment_boundary(self):
        self.d["teacher"].left_on = date(2026, 10, 25)
        self.d["teacher"].save()
        with self.assertRaisesMessage(ValidationError, "employment"):
            schedule.save_entry(self.admin, self.entry, 1)

    def test_unavailable_teacher(self):
        Availability.objects.create(
            teacher=self.d["teacher"], period=self.period, kind="unavailable"
        )
        with self.assertRaisesMessage(ValidationError, "unavailable"):
            schedule.save_entry(self.admin, self.entry, 1)

    def test_break_overlap(self):
        Period.objects.create(
            academic_year=self.d["year"],
            name="Break",
            weekday=0,
            starts_at=time(8, 20),
            ends_at=time(8, 50),
            kind="break",
        )
        with self.assertRaisesMessage(ValidationError, "break"):
            schedule.save_entry(self.admin, self.entry, 1)

    def test_used_period_protected(self):
        schedule.save_entry(self.admin, self.entry, 1)
        self.period.starts_at = time(9)
        with self.assertRaisesMessage(ValidationError, "protected"):
            schedule.save_setup(self.admin, self.period)

    def test_empty_publish_rejected(self):
        with self.assertRaises(ValidationError):
            schedule.transition(self.admin, self.table.pk, "publish")

    def test_copy_and_archive_preserve_entries(self):
        schedule.save_entry(self.admin, self.entry, 1)
        schedule.transition(self.admin, self.table.pk, "publish")
        copy = schedule.copy_table(self.admin, self.table.pk)
        self.assertEqual(copy.state, "draft")
        self.assertEqual(copy.entries.count(), 1)
        schedule.transition(self.admin, self.table.pk, "archive")
        self.assertEqual(self.table.entries.count(), 1)

    def test_published_edit_blocked(self):
        schedule.save_entry(self.admin, self.entry, 1)
        schedule.transition(self.admin, self.table.pk, "publish")
        with self.assertRaises(ValidationError):
            schedule.save_entry(self.admin, self.entry, 2)

    def test_private_timetable_url(self):
        self.login(self.student)
        self.assertEqual(self.client.get(f"/scheduling/{self.table.pk}/").status_code, 404)


class LearningTests(Phase7Fixture):
    def test_teacher_cannot_assign_other_section(self):
        other = TeachingAssignment.objects.create(
            teacher=Teacher.objects.create(first_name="Other", employee_number="T2"),
            academic_year=self.d["year"],
            section=self.d["other_section"],
            subject=self.d["subject"],
        )
        self.assignment.teaching = other
        with self.assertRaises(PermissionDenied):
            learn.save_assignment(self.teacher, self.assignment)

    def test_draft_private(self):
        learn.save_assignment(self.teacher, self.assignment)
        self.assertFalse(ls.visible(self.student).exists())
        self.assertFalse(ls.visible(self.parent).exists())

    def test_scheduled_visibility(self):
        self.assignment.publish_at = NOW + timedelta(hours=1)
        self.homework()
        self.assertFalse(ls.visible(self.student).exists())

    def test_own_published_visible(self):
        self.homework()
        self.assertTrue(ls.visible(self.student).exists())
        self.assertTrue(ls.visible(self.parent).exists())

    def test_guardian_revocation_immediate(self):
        self.homework()
        self.d["guardian"].student_links.all().delete()
        self.assertFalse(ls.visible(self.parent).exists())
        self.assertFalse(notices(self.parent).exists())

    def test_guardian_cannot_submit(self):
        self.homework()
        with self.assertRaises(PermissionDenied):
            learn.submit(self.parent, self.assignment.pk, "Impersonation", final=True)

    def test_cross_class_submit_denied(self):
        self.homework()
        other = make_user("other", "Student")
        self.d["other"].user = other
        self.d["other"].save()
        with self.assertRaises(PermissionDenied):
            learn.submit(other, self.assignment.pk, "Other", final=True)

    def test_draft_and_final_versions_preserved(self):
        self.homework()
        learn.submit(self.student, self.assignment.pk, "Draft", final=False)
        row = learn.submit(self.student, self.assignment.pk, "Final", final=True, expected=1)
        self.assertEqual(row.versions.count(), 2)
        self.assertEqual(row.versions.last().text, "Draft")

    def test_final_cannot_be_replaced(self):
        row = self.submitted()
        with self.assertRaises(ValidationError):
            learn.submit(
                self.student, self.assignment.pk, "Replace", final=True, expected=row.revision
            )

    def test_stale_submission_blocked(self):
        self.homework()
        learn.submit(self.student, self.assignment.pk, "Draft", final=False)
        with self.assertRaises(ValidationError):
            learn.submit(self.student, self.assignment.pk, "Stale", final=True)

    def test_deadline_enforced(self):
        self.assignment.due_at = NOW - timedelta(minutes=1)
        self.homework()
        with self.assertRaisesMessage(ValidationError, "deadline"):
            learn.submit(self.student, self.assignment.pk, "Late", final=True)

    def test_late_label_and_penalty(self):
        self.assignment.due_at = NOW - timedelta(minutes=1)
        self.assignment.late_allowed = True
        self.assignment.late_penalty = Decimal(10)
        row = self.submitted()
        feedback = learn.review(
            self.teacher, row.pk, text="Good", outcome="graded", marks=Decimal(80), released=True
        )
        self.assertTrue(row.versions.first().late)
        self.assertEqual(feedback.marks, Decimal(72))

    def test_feedback_private_until_release(self):
        row = self.submitted()
        learn.review(
            self.teacher, row.pk, text="Private assessment", outcome="graded", marks=Decimal(70)
        )
        self.login(self.student)
        self.assertNotContains(
            self.client.get(f"/learning/{self.assignment.pk}/"), "Private assessment"
        )

    def test_guardian_release_explicit(self):
        row = self.submitted()
        learn.review(
            self.teacher,
            row.pk,
            text="Student only feedback",
            outcome="graded",
            marks=Decimal(70),
            released=True,
        )
        self.login(self.parent)
        self.assertNotContains(
            self.client.get(f"/learning/{self.assignment.pk}/"), "Student only feedback"
        )
        learn.review(
            self.teacher,
            row.pk,
            text="Family feedback",
            outcome="reviewed",
            released=True,
            guardian_visible=True,
        )
        self.assertContains(self.client.get(f"/learning/{self.assignment.pk}/"), "Family feedback")

    def test_marks_bounds(self):
        row = self.submitted()
        with self.assertRaises(ValidationError):
            learn.review(self.teacher, row.pk, text="Invalid", outcome="graded", marks=Decimal(101))

    def test_student_cannot_grade(self):
        row = self.submitted()
        with self.assertRaises(PermissionDenied):
            learn.review(self.student, row.pk, text="Invalid", outcome="graded", marks=Decimal(99))

    def test_return_allows_new_version(self):
        row = self.submitted()
        learn.review(self.teacher, row.pk, text="Revise", outcome="returned", released=True)
        learn.submit(self.student, self.assignment.pk, "Revised", final=True, expected=1)
        self.assertEqual(SubmissionVersion.objects.count(), 2)

    def test_assessment_rules_frozen(self):
        self.submitted()
        self.assignment.refresh_from_db()
        self.assignment.maximum = Decimal(200)
        with self.assertRaises(ValidationError):
            learn.save_assignment(self.teacher, self.assignment, self.assignment.revision)

    def test_upload_validation(self):
        for name, data, content in [
            ("bad.exe", b"MZ", "application/octet-stream"),
            ("bad.pdf", b"fake", "application/pdf"),
            ("bad.png", b"fake", "image/png"),
            ("bad.txt", b"\x00", "text/plain"),
        ]:
            with self.subTest(name=name), self.assertRaises(ValidationError):
                read_private_upload(SimpleUploadedFile(name, data, content_type=content))

    def test_private_file_access(self):
        self.homework()
        row = learn.submit(
            self.student,
            self.assignment.pk,
            "File",
            final=True,
            files=[SimpleUploadedFile("work.txt", b"Private work", content_type="text/plain")],
        )
        file = Attachment.objects.get(version__submission=row)
        self.login(self.parent)
        response = self.client.get(f"/learning/attachments/{file.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/octet-stream")
        self.d["guardian"].student_links.all().delete()
        self.assertEqual(self.client.get(f"/learning/attachments/{file.pk}/").status_code, 404)

    def test_teacher_reassignment_revokes_review(self):
        row = self.submitted()
        TeachingAssignment.objects.filter(pk=self.teaching.pk).update(
            teacher=Teacher.objects.create(first_name="Replacement", employee_number="T2")
        )
        with self.assertRaises(PermissionDenied):
            learn.review(self.teacher, row.pk, text="Denied", outcome="reviewed")

    def test_closed_assignment_blocks_submission(self):
        self.homework()
        learn.transition(self.teacher, self.assignment.pk, "close")
        with self.assertRaises(ValidationError):
            learn.submit(self.student, self.assignment.pk, "Closed", final=True)


class CommunicationTests(Phase7Fixture):
    def test_independent_approval(self):
        row = self.publication()
        with self.assertRaises(ValidationError):
            comm.publication_action(self.admin, row.pk, "publish")
        principal = make_user("principal", "Principal")
        comm.publication_action(principal, row.pk, "publish")
        self.assertTrue(cs.publications(self.student).filter(pk=row.pk).exists())

    def test_staff_event_hidden(self):
        row = self.publication(audience="staff")
        CommunicationPolicy.objects.create(require_approval=False)
        comm.publication_action(self.admin, row.pk, "publish")
        self.assertFalse(cs.publications(self.student).exists())
        self.assertTrue(cs.publications(self.teacher).exists())

    def test_draft_event_hidden(self):
        self.publication()
        self.assertFalse(cs.publications(self.student).exists())

    def test_cancellation_retained(self):
        row = self.publication()
        CommunicationPolicy.objects.create(require_approval=False)
        comm.publication_action(self.admin, row.pk, "publish")
        comm.publication_action(self.admin, row.pk, "cancel", "Weather")
        self.assertEqual(cs.publications(self.student).get().state, "cancelled")
        self.assertEqual(row.history.count(), 3)

    def test_event_does_not_close_school(self):
        from attendance.models import CalendarEvent

        count = CalendarEvent.objects.count()
        self.publication()
        self.assertEqual(CalendarEvent.objects.count(), count)

    def test_guardian_teacher_conversation(self):
        row = comm.send(
            self.parent,
            "Hello teacher",
            recipient=self.teacher,
            student=self.d["own"],
            subject="Learning progress",
        )
        comm.send(self.teacher, "Hello family", conversation=row.pk)
        self.assertEqual(row.messages.count(), 2)

    def test_cross_family_conversation_rejected(self):
        with self.assertRaises(PermissionDenied):
            comm.send(
                self.parent, "Denied", recipient=self.teacher, student=self.d["other"], subject="No"
            )

    def test_student_arbitrary_adult_rejected(self):
        with self.assertRaises(PermissionDenied):
            comm.send(self.student, "Denied", recipient=self.teacher, subject="No")

    def test_revoked_thread_access(self):
        row = comm.send(
            self.parent, "Hello", recipient=self.teacher, student=self.d["own"], subject="Progress"
        )
        self.d["guardian"].student_links.all().delete()
        self.assertFalse(cs.conversations(self.parent).exists())
        self.assertFalse(cs.conversations(self.teacher).exists())
        with self.assertRaises(PermissionDenied):
            comm.send(self.teacher, "Denied", conversation=row.pk)

    def test_reassigned_teacher_thread_access(self):
        row = comm.send(
            self.parent, "Hello", recipient=self.teacher, student=self.d["own"], subject="Progress"
        )
        self.teaching.delete()
        self.assertFalse(cs.conversations(self.teacher).exists())
        with self.assertRaises(PermissionDenied):
            comm.send(self.parent, "Denied", conversation=row.pk)

    def test_message_spoofing_denied(self):
        row = comm.send(
            self.parent, "Hello", recipient=self.teacher, student=self.d["own"], subject="Progress"
        )
        with self.assertRaises(PermissionDenied):
            comm.send(self.d["accountant"], "Spoof", conversation=row.pk)

    def test_rate_limit(self):
        CommunicationPolicy.objects.create(messages_per_hour=1)
        row = comm.send(
            self.parent, "Hello", recipient=self.teacher, student=self.d["own"], subject="Progress"
        )
        with self.assertRaisesMessage(ValidationError, "limit"):
            comm.send(self.parent, "Another", conversation=row.pk)

    def test_duplicate_spam_rejected(self):
        row = comm.send(
            self.parent, "Hello", recipient=self.teacher, student=self.d["own"], subject="Progress"
        )
        with self.assertRaisesMessage(ValidationError, "just sent"):
            comm.send(self.parent, "Hello", conversation=row.pk)

    def test_message_xss_escaped(self):
        row = comm.send(
            self.parent,
            "<script>alert(1)</script>",
            recipient=self.teacher,
            student=self.d["own"],
            subject="Progress",
        )
        self.login(self.teacher)
        response = self.client.get(f"/communications/messages/{row.pk}/")
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, "<script>alert(1)")

    def test_report_and_moderation(self):
        row = comm.send(
            self.parent,
            "Concern",
            recipient=self.teacher,
            student=self.d["own"],
            subject="Progress",
        )
        report = comm.report_message(self.teacher, row.messages.get().pk, "Please review")
        principal = make_user("principal", "Principal")
        comm.moderate(principal, report.pk, "Reviewed and restricted", hide=True, block=True)
        self.assertTrue(Message.objects.get().hidden)
        with self.assertRaises(PermissionDenied):
            comm.send(self.parent, "Again", conversation=row.pk)

    def test_notice_deduplication_and_scope(self):
        from communications.notices import publication_notice

        row = self.publication()
        CommunicationPolicy.objects.create(require_approval=False)
        row = comm.publication_action(self.admin, row.pk, "publish")
        count = Notice.objects.count()
        publication_notice(row)
        self.assertEqual(Notice.objects.count(), count)
        self.assertEqual(notices(self.student).count(), 1)

    def test_csrf_on_mutations(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin, backend=BACKEND)
        for path in [
            "/scheduling/new/",
            "/learning/new/",
            "/communications/publications/new/",
            "/communications/messages/new/",
        ]:
            with self.subTest(path=path):
                self.assertEqual(client.post(path, {}).status_code, 403)

    def test_anonymous_endpoints(self):
        for path in [
            "/scheduling/",
            "/learning/",
            "/communications/",
            "/communications/messages/",
            "/communications/calendar/",
        ]:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 302)

    def test_all_primary_screens_render(self):
        self.homework()
        schedule.save_entry(self.admin, self.entry, 1)
        schedule.transition(self.admin, self.table.pk, "publish")
        for user in [self.admin, self.student, self.parent, self.teacher]:
            self.login(user)
            for path in [
                "/scheduling/",
                "/learning/",
                "/communications/",
                "/communications/messages/",
                "/communications/calendar/",
                f"/scheduling/{self.table.pk}/",
                f"/learning/{self.assignment.pk}/",
                "/portals/notifications/",
            ]:
                with self.subTest(user=user.username, path=path):
                    self.assertEqual(self.client.get(path).status_code, 200)
