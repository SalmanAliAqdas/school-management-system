from datetime import date

from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings

from analytics.selectors import executive_metrics
from people.models import GuardianStudent, Student

from .helpers import BACKEND, make_school_data, make_user


class Phase9AnalyticsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.d = make_school_data()
        cls.principal = make_user("analytics-principal", "Principal")
        cls.admin = make_user("analytics-admin", "System Administrator")
        cls.inventory = make_user("analytics-inventory", "Inventory Manager")

    def query(self):
        return {
            "academic_year": self.d["year"].pk,
            "starts_on": self.d["year"].starts_on.isoformat(),
            "ends_on": date(2026, 10, 24).isoformat(),
        }

    def test_executive_counts_saved_active_placements(self):
        values = executive_metrics(
            self.admin,
            self.d["year"],
            self.d["year"].starts_on,
            date(2026, 10, 24),
        )
        self.assertEqual(values["active_students"], 2)
        self.assertEqual(sum(row["total"] for row in values["classes"]), 2)
        self.assertIsNone(values["student_attendance"]["percentage"])

    def test_executive_requires_explicit_permission(self):
        self.client.force_login(self.inventory, backend=BACKEND)
        self.assertEqual(self.client.get("/analytics/", self.query()).status_code, 403)
        self.client.force_login(self.principal, backend=BACKEND)
        self.assertEqual(self.client.get("/analytics/", self.query()).status_code, 200)

    def test_principal_does_not_receive_salary_aggregate(self):
        self.assertFalse(self.principal.has_perm("payroll.view_all_payroll"))
        values = executive_metrics(
            self.principal,
            self.d["year"],
            self.d["year"].starts_on,
            date(2026, 10, 24),
        )
        self.assertNotIn("payroll", values)

    def test_csv_export_is_formula_safe_and_audited(self):
        Student.objects.filter(pk=self.d["own"].pk).update(first_name="=FORMULA")
        self.client.force_login(self.admin, backend=BACKEND)
        response = self.client.get(
            "/analytics/reports/students/", {**self.query(), "format": "csv"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"'=FORMULA", response.content)
        self.assertIn("private", response["Cache-Control"])
        self.assertIn("no-store", response["Cache-Control"])

    def test_guardian_progress_scope_rejects_unlinked_student(self):
        self.client.force_login(self.d["parent"], backend=BACKEND)
        self.assertEqual(
            self.client.get(f"/analytics/students/{self.d['own'].pk}/").status_code, 200
        )
        self.assertEqual(
            self.client.get(f"/analytics/students/{self.d['other'].pk}/").status_code, 404
        )
        GuardianStudent.objects.filter(guardian=self.d["guardian"], student=self.d["own"]).delete()
        self.assertEqual(
            self.client.get(f"/analytics/students/{self.d['own'].pk}/").status_code, 404
        )

    def test_invalid_date_window_is_rejected_without_querying(self):
        self.client.force_login(self.admin, backend=BACKEND)
        response = self.client.get(
            "/analytics/",
            {
                "academic_year": self.d["year"].pk,
                "starts_on": "2026-10-24",
                "ends_on": "2026-01-01",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ordered date range")

    def test_health_endpoints_are_minimal_and_private(self):
        for path, expected in (
            ("/health/live/", {"status": "alive"}),
            ("/health/", {"status": "ok"}),
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), expected)
            self.assertIn("no-cache", response["Cache-Control"])

    @override_settings(ALLOW_DEMO_DATA=True)
    def test_demo_guide_requires_reserved_demo_identity(self):
        self.client.force_login(self.admin, backend=BACKEND)
        self.assertEqual(self.client.get("/demo/guide/").status_code, 404)
        demo = make_user("demo.phase9", "System Administrator")
        self.client.force_login(demo, backend=BACKEND)
        self.assertEqual(self.client.get("/demo/guide/").status_code, 200)

    def test_export_requires_separate_permission(self):
        reporter = make_user("analytics-reporter", "Inventory Manager")
        reporter.user_permissions.add(
            Permission.objects.get(codename="view_reporting_center"),
            Permission.objects.get(codename="view_all_students"),
        )
        self.client.force_login(reporter, backend=BACKEND)
        self.assertEqual(
            self.client.get(
                "/analytics/reports/students/", {**self.query(), "format": "csv"}
            ).status_code,
            403,
        )

    def test_authorized_navigation_links_to_live_analytics(self):
        self.client.force_login(self.admin, backend=BACKEND)
        response = self.client.get("/analytics/", self.query())
        self.assertContains(response, 'href="/analytics/"')
        self.assertNotContains(response, 'Reports<span class="nav-planned">Soon')
