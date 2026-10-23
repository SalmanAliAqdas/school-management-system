from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth.models import Group
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from academics.models import Subject, TeachingAssignment
from attendance.models import AbsenceNotification
from attendance.services import save_student_register
from core.models import SchoolSettings
from examinations.services import save_marks
from finance.ledger import student_balance_map, student_balances
from finance.models import FinanceNotice
from finance.payments import invoice_total_map, invoice_totals
from people.models import Enrollment, GuardianStudent, Student
from portals.notifications import inbox, unread_count
from portals.selectors import assignment_writable
from portals.services import child_summaries

from .helpers import BACKEND, PASSWORD, make_school_data, make_user
from .test_attendance import DAY, AttendanceFixtureMixin
from .test_examinations import ExaminationFixture
from .test_finance import FinanceFixture


def child_url(role, student, section="profile"):
    return reverse("portals:student", args=[role, student.pk, section])


class PortalAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.data = make_school_data()
        SchoolSettings.objects.create(name="Fictional Portal School")

    def login(self, key="student_user"):
        self.client.force_login(self.data[key], backend=BACKEND)

    def test_anonymous_portal_and_private_pages_require_login(self):
        for path in (
            "/portals/student/",
            "/portals/parent/",
            "/portals/teacher/",
            "/portals/notifications/",
            "/portals/settings/",
            child_url("student", self.data["own"]),
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 302)

    def test_student_dashboard_uses_real_identity_and_unknown_values(self):
        self.login()
        response = self.client.get("/portals/student/")
        self.assertContains(response, "TEST-001")
        self.assertContains(response, "Not recorded")
        self.assertContains(response, "Unavailable")
        self.assertNotContains(response, "TEST-002")

    def test_student_cannot_open_any_peer_center(self):
        self.login()
        for section in ("profile", "attendance", "results", "reports", "fees", "calendar"):
            with self.subTest(section=section):
                self.assertEqual(
                    self.client.get(child_url("student", self.data["other"], section)).status_code,
                    404,
                )

    def test_guardian_multiple_children_and_selected_identity(self):
        GuardianStudent.objects.create(
            guardian=self.data["guardian"], student=self.data["other"], relationship="Guardian"
        )
        self.login("parent")
        response = self.client.get("/portals/parent/")
        self.assertEqual(len(response.context["summaries"]), 2)
        response = self.client.get(child_url("parent", self.data["other"]))
        self.assertEqual(response.context["selected_student"], self.data["other"])

    def test_child_switch_preserves_requested_center(self):
        self.login("parent")
        response = self.client.get(
            "/portals/parent/select-child/", {"child": self.data["own"].pk, "section": "attendance"}
        )
        self.assertRedirects(
            response,
            child_url("parent", self.data["own"], "attendance"),
            fetch_redirect_response=False,
        )

    def test_child_switch_rejects_unrelated_or_malformed_identifiers(self):
        self.login("parent")
        for identifier in (self.data["other"].pk, "invalid", ""):
            self.assertEqual(
                self.client.get("/portals/parent/select-child/", {"child": identifier}).status_code,
                404,
            )

    def test_child_switch_cannot_redirect_to_an_external_site(self):
        self.login("parent")
        response = self.client.get(
            "/portals/parent/select-child/",
            {"child": self.data["own"].pk, "section": "https://example.invalid"},
        )
        self.assertRedirects(
            response, child_url("parent", self.data["own"]), fetch_redirect_response=False
        )

    def test_revoked_link_blocks_all_centers_and_child_switch(self):
        self.login("parent")
        self.data["guardian"].student_links.all().delete()
        for section in ("profile", "attendance", "results", "reports", "fees", "calendar"):
            self.assertEqual(
                self.client.get(child_url("parent", self.data["own"], section)).status_code, 404
            )
        self.assertEqual(
            self.client.get(
                "/portals/parent/select-child/", {"child": self.data["own"].pk}
            ).status_code,
            404,
        )

    def test_role_switch_is_post_only_and_cannot_escalate(self):
        self.login()
        self.assertEqual(self.client.get("/portals/switch/").status_code, 405)
        self.assertEqual(self.client.post("/portals/switch/", {"role": "admin"}).status_code, 403)
        self.assertNotIn("selected_portal", self.client.session)

    def test_permitted_role_switch_remembers_choice(self):
        self.data["teacher_user"].groups.add(Group.objects.get(name="Parent or Guardian"))
        self.login("teacher_user")
        response = self.client.post("/portals/switch/", {"role": "parent"})
        self.assertRedirects(response, "/dashboard/parent/", fetch_redirect_response=False)
        self.assertEqual(self.client.session["selected_portal"], "parent")
        self.assertRedirects(
            self.client.get("/"), "/dashboard/parent/", fetch_redirect_response=False
        )

    def test_removed_role_invalidates_saved_preference(self):
        self.login()
        self.client.post("/portals/switch/", {"role": "student"})
        self.data["student_user"].groups.clear()
        self.assertEqual(self.client.get("/portals/student/").status_code, 403)
        self.assertEqual(self.client.get("/").status_code, 403)

    def test_administrative_secondary_role_does_not_enlarge_student_portal(self):
        self.data["student_user"].groups.add(Group.objects.get(name="School Administrator"))
        self.login()
        response = self.client.get("/portals/student/")
        self.assertEqual(len(response.context["summaries"]), 1)
        self.assertEqual(self.client.get(child_url("student", self.data["other"])).status_code, 404)

    def test_invalid_year_and_invalid_month_fail_cleanly(self):
        self.login()
        for params in (
            {"academic_year": "invalid"},
            {"academic_year": "99999999"},
            {"month": "bad"},
        ):
            self.assertEqual(
                self.client.get(
                    child_url("student", self.data["own"], "attendance"), params
                ).status_code,
                404,
            )

    def test_no_enrollment_provides_honest_empty_centers(self):
        account = make_user("portalempty", "Student")
        self.data["unassigned"].user = account
        self.data["unassigned"].save()
        self.client.force_login(account, backend=BACKEND)
        for section in ("profile", "attendance", "results", "reports", "calendar"):
            self.assertEqual(
                self.client.get(child_url("student", self.data["unassigned"], section)).status_code,
                200,
            )

    def test_profile_does_not_reveal_enrollment_notes(self):
        Enrollment.objects.filter(student=self.data["own"], is_active=True).update(
            notes="Private administrative note"
        )
        self.login()
        self.assertNotContains(
            self.client.get(child_url("student", self.data["own"])), "Private administrative note"
        )

    def test_settings_only_update_safe_fields(self):
        self.login("parent")
        self.client.post(
            "/portals/settings/",
            {
                "phone": "Fictional office number",
                "density": "compact",
                "email": "forged@example.invalid",
                "is_superuser": "1",
            },
        )
        self.data["guardian"].refresh_from_db()
        self.data["parent"].refresh_from_db()
        self.assertEqual(self.data["guardian"].phone, "Fictional office number")
        self.assertEqual(self.client.session["display_density"], "compact")
        self.assertFalse(self.data["parent"].is_superuser)
        self.assertEqual(self.data["parent"].email, "guardian@example.invalid")

    def test_invalid_display_choice_is_rejected(self):
        self.login()
        response = self.client.post("/portals/settings/", {"density": "<script>"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("display_density", self.client.session)

    def test_password_change_uses_validation_and_keeps_session(self):
        self.login()
        response = self.client.post(
            "/portals/settings/password/",
            {
                "old_password": PASSWORD,
                "new_password1": "Fictional-Changed-Portal-Phrase-978!",
                "new_password2": "Fictional-Changed-Portal-Phrase-978!",
            },
        )
        self.assertRedirects(response, "/portals/settings/")
        self.data["student_user"].refresh_from_db()
        self.assertTrue(
            self.data["student_user"].check_password("Fictional-Changed-Portal-Phrase-978!")
        )
        self.assertEqual(self.client.get("/portals/student/").status_code, 200)

    def test_wrong_current_password_cannot_change_password(self):
        self.login()
        self.client.post(
            "/portals/settings/password/",
            {"old_password": "wrong", "new_password1": "short", "new_password2": "short"},
        )
        self.data["student_user"].refresh_from_db()
        self.assertTrue(self.data["student_user"].check_password(PASSWORD))

    def test_all_portal_mutations_enforce_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.data["student_user"], backend=BACKEND)
        for path in (
            "/portals/switch/",
            "/portals/settings/",
            "/portals/settings/password/",
            "/portals/notifications/finance/1/read/",
        ):
            self.assertEqual(client.post(path, {}).status_code, 403)

    def test_personal_centers_reject_post(self):
        self.login()
        for section in ("profile", "attendance", "results", "calendar"):
            self.assertEqual(
                self.client.post(child_url("student", self.data["own"], section), {}).status_code,
                405,
            )

    def test_teacher_cannot_use_personal_finance_center(self):
        self.login("teacher_user")
        self.assertEqual(
            self.client.get(child_url("teacher", self.data["own"], "fees")).status_code, 404
        )
        self.assertEqual(self.client.get("/finance/students/").status_code, 403)

    def test_current_assignment_and_unrelated_class_isolation(self):
        self.login("teacher_user")
        own_assignment = TeachingAssignment.objects.get(teacher=self.data["teacher"])
        response = self.client.get(reverse("portals:classroom", args=[own_assignment.pk]))
        self.assertContains(response, "TEST-001")
        self.assertNotContains(response, "TEST-002")
        self.assertEqual(
            self.client.get(
                reverse("portals:teacher_student", args=[own_assignment.pk, self.data["other"].pk])
            ).status_code,
            404,
        )

    def test_teacher_student_detail_omits_family_and_finance_information(self):
        self.login("teacher_user")
        assignment = TeachingAssignment.objects.get(teacher=self.data["teacher"])
        response = self.client.get(
            reverse("portals:teacher_student", args=[assignment.pk, self.data["own"].pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Fictional Guardian")
        self.assertNotContains(response, "Outstanding receivable")

    def test_removed_assignment_immediately_blocks_classroom(self):
        self.login("teacher_user")
        assignment = TeachingAssignment.objects.get(teacher=self.data["teacher"])
        url = reverse("portals:classroom", args=[assignment.pk])
        assignment.delete()
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_historical_year_is_read_only_even_if_still_open(self):
        assignment = TeachingAssignment.objects.get(teacher=self.data["teacher"])
        assignment.academic_year = self.data["old_year"]
        assignment.save()
        self.assertFalse(assignment_writable(assignment))

    def test_teacher_year_filter_cannot_select_unassigned_year(self):
        self.login("teacher_user")
        self.assertEqual(
            self.client.get(
                "/portals/teacher/classes/", {"academic_year": self.data["old_year"].pk}
            ).status_code,
            404,
        )

    def test_historical_class_roster_has_no_edit_action(self):
        self.data["teacher"].joined_on = self.data["old_year"].starts_on
        self.data["teacher"].save()
        assignment = TeachingAssignment.objects.create(
            teacher=self.data["teacher"],
            academic_year=self.data["old_year"],
            section=self.data["other_section"],
            subject=self.data["subject"],
        )
        self.login("teacher_user")
        response = self.client.get(reverse("portals:classroom", args=[assignment.pk]))
        self.assertContains(response, "Historical / read-only")
        self.assertNotContains(response, "Open attendance register")

    def test_teacher_dashboard_queries_do_not_grow_per_assignment(self):
        self.login("teacher_user")
        with CaptureQueriesContext(connection) as one:
            self.client.get("/portals/teacher/")
        for number in range(8):
            subject = Subject.objects.create(code=f"PORTAL-{number}", name=f"Subject {number}")
            TeachingAssignment.objects.create(
                teacher=self.data["teacher"],
                academic_year=self.data["year"],
                section=self.data["section"],
                subject=subject,
            )
        with CaptureQueriesContext(connection) as many:
            response = self.client.get("/portals/teacher/")
        self.assertEqual(len(response.context["work"]), 9)
        self.assertLessEqual(len(many), len(one) + 1)

    def test_family_summary_query_count_does_not_grow_per_child(self):
        user = self.data["parent"]
        # Warm capability caches before comparing the read service itself.
        user.get_all_permissions()
        children = [self.data["own"]]
        with CaptureQueriesContext(connection) as one:
            child_summaries(user, children, self.data["year"], date(2026, 10, 23), role="parent")
        for index in range(8):
            child = Student.objects.create(
                first_name="Fictional",
                last_name=f"Sibling {index}",
                admission_number=f"PORTAL-{index}",
            )
            children.append(child)
            GuardianStudent.objects.create(
                guardian=self.data["guardian"], student=child, relationship="Guardian"
            )
        with CaptureQueriesContext(connection) as many:
            child_summaries(user, children, self.data["year"], date(2026, 10, 23), role="parent")
        self.assertLessEqual(len(many), len(one) + 1)
        self.assertLessEqual(len(many), 13)

    def test_family_overview_is_paginated(self):
        for index in range(13):
            child = Student.objects.create(
                first_name="Fictional",
                last_name=f"Sibling {index}",
                admission_number=f"PAGE-{index}",
            )
            GuardianStudent.objects.create(
                guardian=self.data["guardian"], student=child, relationship="Guardian"
            )
        self.login("parent")
        response = self.client.get("/portals/parent/", {"page": 2})
        self.assertEqual(response.context["page_obj"].number, 2)
        self.assertEqual(len(response.context["summaries"]), 2)


class PortalAttendanceTests(AttendanceFixtureMixin, TestCase):
    def create_register(self, status="present"):
        placement = Enrollment.objects.get(
            student=self.data["own"], academic_year=self.data["year"]
        )
        return save_student_register(
            self.actor,
            year_id=self.data["year"].pk,
            section_id=self.data["section"].pk,
            day=DAY,
            rows={str(placement.pk): {"status": status}},
            final=True,
        )

    def test_portal_attendance_reuses_policy_percentage(self):
        self.create_register("late")
        self.client.force_login(self.data["student_user"], backend=BACKEND)
        response = self.client.get(
            child_url("student", self.data["own"], "attendance"), {"month": "2026-10"}
        )
        self.assertEqual(response.context["stats"]["percentage"], Decimal("100.00"))
        self.assertEqual(response.context["stats"]["late"], 1)

    def test_missing_days_do_not_count_as_absent(self):
        self.client.force_login(self.data["student_user"], backend=BACKEND)
        response = self.client.get(
            child_url("student", self.data["own"], "attendance"), {"month": "2026-10"}
        )
        self.assertEqual(response.context["stats"]["absent"], 0)
        self.assertIsNone(response.context["stats"]["percentage"])
        self.assertContains(response, "Not recorded")

    def test_absence_notification_has_original_read_state(self):
        self.create_register("absent")
        user = self.data["parent"]
        self.client.force_login(user, backend=BACKEND)
        notice = AbsenceNotification.objects.get(recipient=user)
        self.assertEqual(unread_count(user), 1)
        self.assertContains(self.client.get("/portals/notifications/"), "recorded absence")
        url = reverse("portals:notification_read", args=["attendance", notice.pk])
        self.client.post(url)
        notice.refresh_from_db()
        self.assertIsNotNone(notice.read_at)
        self.assertEqual(unread_count(user), 0)
        self.assertEqual(AbsenceNotification.objects.count(), 1)

    def test_revoked_guardian_cannot_read_or_mark_old_notice(self):
        self.create_register("absent")
        notice = AbsenceNotification.objects.get(recipient=self.data["parent"])
        self.client.force_login(self.data["parent"], backend=BACKEND)
        self.data["guardian"].student_links.all().delete()
        self.assertNotContains(self.client.get("/portals/notifications/"), "recorded absence")
        self.assertEqual(
            self.client.post(
                reverse("portals:notification_read", args=["attendance", notice.pk])
            ).status_code,
            404,
        )

    def test_guessed_notification_source_and_ids_fail_closed(self):
        self.create_register("absent")
        notice = AbsenceNotification.objects.get(recipient=self.data["parent"])
        self.client.force_login(self.data["student_user"], backend=BACKEND)
        self.assertEqual(
            self.client.post(
                reverse("portals:notification_read", args=["attendance", notice.pk])
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post("/portals/notifications/unknown/1/read/").status_code, 404
        )

    def test_notification_category_child_and_unread_filters(self):
        self.create_register("absent")
        self.client.force_login(self.data["parent"], backend=BACKEND)
        response = self.client.get(
            "/portals/notifications/",
            {"category": "attendance", "unread": 1, "child": self.data["own"].pk},
        )
        self.assertEqual(response.context["page_obj"].paginator.count, 1)
        self.assertEqual(
            self.client.get("/portals/notifications/", {"category": "unknown"}).status_code, 404
        )
        self.assertEqual(
            self.client.get(
                "/portals/notifications/", {"child": self.data["other"].pk}
            ).status_code,
            404,
        )

    def test_teacher_cannot_write_before_employment(self):
        self.data["teacher"].joined_on = date(2026, 10, 6)
        self.data["teacher"].save()
        placement = Enrollment.objects.get(
            student=self.data["own"], academic_year=self.data["year"]
        )
        from django.core.exceptions import PermissionDenied

        with self.assertRaises(PermissionDenied):
            save_student_register(
                self.data["teacher_user"],
                year_id=self.data["year"].pk,
                section_id=self.data["section"].pk,
                day=DAY,
                rows={str(placement.pk): {"status": "present"}},
            )


class PortalExaminationTests(ExaminationFixture, TestCase):
    def amend_publication(self, withheld):
        from examinations.services import decide_amendment, request_amendment

        self.candidate.refresh_from_db()
        self.session.refresh_from_db()
        request = request_amendment(
            self.controller,
            self.candidate.pk,
            teacher_remarks=self.candidate.teacher_remarks,
            principal_remarks=self.candidate.principal_remarks,
            withheld=withheld,
            withholding_reason="Confidential review" if withheld else "",
            expected_version=self.session.version,
            reason="Fictional reviewed amendment",
        )
        return decide_amendment(
            self.principal, request.pk, approve=True, reason="Independent review"
        )

    def test_withholding_suppresses_current_and_historical_personal_results(self):
        original = self.publish()
        self.amend_publication(True)
        self.client.force_login(self.data["student_user"], backend=BACKEND)
        for section in ("results", "reports"):
            response = self.client.get(child_url("student", self.data["own"], section))
            self.assertEqual(response.context["page_obj"].paginator.count, 0)
        self.assertEqual(
            self.client.get(
                reverse("examinations:report", args=[original.pk]), {"format": "pdf"}
            ).status_code,
            404,
        )
        self.assertIsNone(self.client.get("/portals/student/").context["summaries"][0]["result"])

    def test_released_correction_retains_authorized_report_versions(self):
        self.publish()
        self.amend_publication(True)
        self.amend_publication(False)
        self.client.force_login(self.data["parent"], backend=BACKEND)
        response = self.client.get(child_url("parent", self.data["own"], "reports"))
        self.assertEqual(response.context["page_obj"].paginator.count, 2)
        response = self.client.get(child_url("parent", self.data["own"], "results"))
        self.assertEqual(response.context["page_obj"].paginator.count, 1)

    def test_draft_results_never_appear_in_portal(self):
        self.open()
        self.mark(submit=False)
        self.client.force_login(self.data["student_user"], backend=BACKEND)
        response = self.client.get(child_url("student", self.data["own"], "results"))
        self.assertEqual(response.context["page_obj"].paginator.count, 0)

    def test_published_report_and_pdf_links_are_authorized(self):
        result = self.publish()
        self.client.force_login(self.data["student_user"], backend=BACKEND)
        response = self.client.get(child_url("student", self.data["own"], "results"))
        self.assertContains(response, str(result.pk))
        pdf = self.client.get(reverse("examinations:report", args=[result.pk]), {"format": "pdf"})
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.content.startswith(b"%PDF-"))

    def test_guardian_unlink_blocks_report_and_pdf(self):
        result = self.publish()
        self.data["guardian"].student_links.all().delete()
        self.client.force_login(self.data["parent"], backend=BACKEND)
        for path in (
            child_url("parent", self.data["own"], "reports"),
            reverse("examinations:report", args=[result.pk]) + "?format=pdf",
        ):
            self.assertEqual(self.client.get(path).status_code, 404)

    def test_teacher_subject_view_reuses_published_snapshot(self):
        self.publish()
        self.client.force_login(self.teacher, backend=BACKEND)
        assignment = TeachingAssignment.objects.get(teacher=self.data["teacher"])
        # The fixture's default hire date is after the test examination; use a dated hire.
        self.data["teacher"].joined_on = date(2026, 8, 1)
        self.data["teacher"].save()
        response = self.client.get(
            reverse("portals:teacher_student", args=[assignment.pk, self.data["own"].pk])
        )
        self.assertTrue(response.context["subject_history"])
        self.assertContains(response, "Mathematics")

    def test_historical_marks_assignment_does_not_grant_permanent_writes(self):
        self.open()
        from django.core.exceptions import PermissionDenied

        with patch(
            "attendance.calendar.school_now",
            return_value=datetime(2028, 1, 3, tzinfo=ZoneInfo("Asia/Karachi")),
        ):
            with self.assertRaises(PermissionDenied):
                save_marks(
                    self.teacher,
                    self.sheet.pk,
                    {str(self.candidate.pk): {"status": "assessed", "marks": "80"}},
                    expected_version=0,
                )


class PortalFinanceTests(FinanceFixture, TestCase):
    def test_invoice_batch_query_count_does_not_grow_per_invoice(self):
        from finance.billing import generate_invoices, issue_invoice

        invoice = self.invoice()
        from finance.models import Invoice

        outcome = generate_invoices(self.accountant, self.cycle.pk, [self.data["other"]])
        second = issue_invoice(self.accountant, outcome["generated"][0].pk)
        with CaptureQueriesContext(connection) as one:
            invoice_total_map([invoice])
        with CaptureQueriesContext(connection) as many:
            invoice_total_map(list(Invoice.objects.filter(pk__in=[invoice.pk, second.pk])))
        self.assertLessEqual(len(many), len(one) + 1)

    def test_batched_totals_preserve_reversal_and_void_rules(self):
        invoice = self.invoice()
        payment = self.payment("4000", invoice)
        self.approve("reverse_payment", payment=payment)
        self.assertEqual(invoice_total_map([invoice])[invoice.pk], invoice_totals(invoice))
        self.assertEqual(
            student_balance_map([self.student.pk])[self.student.pk], student_balances(self.student)
        )
        self.approve("void", invoice=invoice)
        invoice.refresh_from_db()
        self.assertEqual(invoice_total_map([invoice])[invoice.pk], invoice_totals(invoice))

    def test_calendar_contains_only_authorized_issued_invoice(self):
        invoice = self.invoice()
        self.client.force_login(self.data["student_user"], backend=BACKEND)
        response = self.client.get(child_url("student", self.student, "calendar"))
        self.assertContains(response, invoice.number)

    def test_batched_balances_equal_ledger_service(self):
        invoice = self.invoice()
        self.payment("4000", invoice)
        self.assertEqual(
            student_balance_map([self.student.pk])[self.student.pk], student_balances(self.student)
        )

    def test_batched_invoice_totals_equal_existing_allocation_service(self):
        invoice = self.invoice()
        self.payment("4000", invoice)
        self.assertEqual(invoice_total_map([invoice])[invoice.pk], invoice_totals(invoice))

    def test_student_fee_page_displays_real_partial_payment(self):
        invoice = self.invoice()
        self.payment("4000", invoice)
        self.client.force_login(self.data["student_user"], backend=BACKEND)
        response = self.client.get(child_url("student", self.student, "fees"))
        self.assertContains(response, "6000.00")
        self.assertEqual(response.context["balances"]["owed"], Decimal("6000"))

    def test_disabled_finance_policy_hides_summary_and_denies_fee_center(self):
        self.invoice()
        self.settings.student_portal = False
        self.settings.save()
        self.data["student_user"].groups.add(Group.objects.get(name="School Administrator"))
        self.client.force_login(self.data["student_user"], backend=BACKEND)
        self.assertEqual(
            self.client.get(child_url("student", self.student, "fees")).status_code, 403
        )
        self.assertIsNone(self.client.get("/portals/student/").context["summaries"][0]["balance"])

    def test_family_finance_and_notification_revoke_immediately(self):
        self.invoice()
        user = self.data["parent"]
        notice = FinanceNotice.objects.filter(recipient=user).first()
        self.assertIsNotNone(notice)
        self.client.force_login(user, backend=BACKEND)
        self.assertEqual(
            self.client.get(child_url("parent", self.student, "fees")).status_code, 200
        )
        self.data["guardian"].student_links.all().delete()
        self.assertEqual(inbox(user, category="finance").count(), 0)
        self.assertEqual(
            self.client.post(
                reverse("portals:notification_read", args=["finance", notice.pk])
            ).status_code,
            404,
        )

    def test_notification_pagination_does_not_create_source_rows(self):
        self.invoice()
        for index in range(25):
            FinanceNotice.objects.create(
                recipient=self.data["parent"],
                student=self.student,
                kind="reminder",
                event_key=f"portal-notice-{index}",
            )
        self.client.force_login(self.data["parent"], backend=BACKEND)
        count = FinanceNotice.objects.count()
        response = self.client.get("/portals/notifications/", {"page": 2})
        self.assertEqual(response.context["page_obj"].number, 2)
        self.client.get("/portals/notifications/")
        self.assertEqual(FinanceNotice.objects.count(), count)
