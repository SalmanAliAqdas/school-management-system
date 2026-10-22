from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse

from academics.models import TeachingAssignment
from audit.models import AuditEvent
from people.selectors import enrollments_visible_to, students_visible_to

from .helpers import BACKEND, make_school_data, make_user


class ObjectPermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.data = make_school_data()

    def sign_in(self, key):
        user = self.data[key]
        self.client.force_login(user, backend=BACKEND)
        return user

    def detail(self, key):
        return reverse("people:student_detail", args=[self.data[key].pk])

    def test_student_cannot_read_another_student(self):
        user = self.sign_in("student_user")
        self.assertQuerySetEqual(students_visible_to(user), [self.data["own"]])
        self.assertEqual(self.client.get(self.detail("own")).status_code, 200)
        self.assertEqual(self.client.get(self.detail("other")).status_code, 404)

    def test_guardian_only_reads_explicitly_linked_child(self):
        user = self.sign_in("parent")
        self.assertQuerySetEqual(students_visible_to(user), [self.data["own"]])
        self.assertEqual(self.client.get(self.detail("own")).status_code, 200)
        self.assertEqual(self.client.get(self.detail("other")).status_code, 404)

    def test_teacher_only_reads_assigned_class_and_year(self):
        user = self.sign_in("teacher_user")
        self.assertQuerySetEqual(students_visible_to(user), [self.data["own"]])
        self.assertEqual(self.client.get(self.detail("own")).status_code, 200)
        self.assertEqual(self.client.get(self.detail("other")).status_code, 404)

    def test_teacher_does_not_see_unassigned_history(self):
        self.sign_in("teacher_user")
        response = self.client.get(self.detail("own"))
        self.assertContains(response, "2026–2027")
        self.assertNotContains(response, "2025–2026")

    def test_assignment_to_wrong_year_grants_no_access(self):
        TeachingAssignment.objects.all().update(academic_year=self.data["old_year"])
        user = self.sign_in("teacher_user")
        self.assertFalse(students_visible_to(user).exists())
        self.assertEqual(self.client.get(self.detail("own")).status_code, 404)

    def test_removing_link_immediately_revokes_access(self):
        self.sign_in("parent")
        self.data["guardian"].student_links.all().delete()
        self.assertEqual(self.client.get(self.detail("own")).status_code, 404)

    def test_accountant_cannot_read_students_or_change_marks(self):
        user = self.sign_in("accountant")
        self.assertFalse(user.has_perm("people.view_student"))
        self.assertFalse(user.has_perm("examinations.change_mark"))
        self.assertFalse(students_visible_to(user).exists())
        self.assertEqual(self.client.get("/students/").status_code, 403)
        self.assertEqual(self.client.post(self.detail("own"), {"marks": "100"}).status_code, 403)

    def test_administrator_has_explicit_global_access(self):
        user = self.sign_in("admin")
        self.assertEqual(students_visible_to(user).count(), 3)
        self.assertEqual(self.client.get(self.detail("other")).status_code, 200)

    def test_staff_flag_does_not_bypass_admin_boundary(self):
        user = self.data["admin"]
        user.is_staff = True
        user.save()
        self.client.force_login(user, backend=BACKEND)
        self.assertRedirects(
            self.client.get("/admin/"), "/admin/login/?next=/admin/", fetch_redirect_response=False
        )

    def test_profile_without_capability_does_not_grant_access(self):
        self.data["student_user"].groups.clear()
        user = self.sign_in("student_user")
        self.assertFalse(students_visible_to(user).exists())

    def test_read_permission_without_profile_has_empty_scope(self):
        user = make_user("reader")
        user.user_permissions.add(
            Permission.objects.get(codename="view_student", content_type__app_label="people")
        )
        self.client.force_login(user, backend=BACKEND)
        response = self.client.get("/students/")
        self.assertContains(response, "No student records")
        self.assertEqual(self.client.get(self.detail("own")).status_code, 404)

    def test_multi_role_scope_is_union_and_dashboard_switching_works(self):
        user = self.data["teacher_user"]
        user.groups.add(Group.objects.get(name="Student"))
        self.data["other"].user = user
        self.data["other"].save()
        self.client.force_login(user, backend=BACKEND)
        self.assertEqual(students_visible_to(user).count(), 2)
        self.assertRedirects(self.client.get("/"), "/dashboard/teacher/")
        self.assertEqual(self.client.get("/dashboard/student/").status_code, 200)

    def test_search_cannot_escape_scope_and_handles_script_input(self):
        self.sign_in("student_user")
        response = self.client.get("/students/", {"q": "TEST-002"})
        self.assertEqual(response.context["page_obj"].paginator.count, 0)
        response = self.client.get("/students/", {"q": '<script>alert("x")</script>'})
        self.assertNotContains(response, '<script>alert("x")</script>')

    def test_detail_access_is_audited(self):
        self.sign_in("student_user")
        self.client.get(self.detail("own"))
        self.assertTrue(
            AuditEvent.objects.filter(
                event="student.viewed",
                actor=self.data["student_user"],
                target=str(self.data["own"].pk),
            ).exists()
        )

    def test_read_views_reject_post_and_keep_database_unchanged(self):
        self.sign_in("admin")
        self.assertEqual(
            self.client.post(self.detail("own"), {"first_name": "Changed"}).status_code, 405
        )
        self.data["own"].refresh_from_db()
        self.assertEqual(self.data["own"].first_name, "Fictional")

    def test_dashboard_chart_is_scoped_to_real_enrollments(self):
        self.sign_in("teacher_user")
        response = self.client.get("/dashboard/teacher/")
        self.assertEqual(response.context["student_count"], 1)
        self.assertEqual(sum(row["total"] for row in response.context["chart_data"]), 1)

    def test_unassigned_teacher_gets_honest_empty_state(self):
        TeachingAssignment.objects.all().delete()
        self.sign_in("teacher_user")
        response = self.client.get("/dashboard/teacher/")
        self.assertEqual(response.context["student_count"], 0)
        self.assertEqual(response.context["chart_data"], [])
        self.assertContains(response, "No current enrollment records")

    def test_superuser_has_access(self):
        user = make_user("super", is_staff=True, is_superuser=True)
        self.client.force_login(user, backend=BACKEND)
        self.assertEqual(self.client.get("/admin/").status_code, 200)
        self.assertEqual(students_visible_to(user).count(), 3)

    def test_inactive_user_selector_is_empty(self):
        user = self.data["admin"]
        user.is_active = False
        self.assertFalse(students_visible_to(user).exists())
        self.assertFalse(enrollments_visible_to(user).exists())
