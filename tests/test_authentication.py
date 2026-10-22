import re

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from accounts.roles import ROLE_PERMISSIONS, sync_roles
from audit.models import AuditEvent

from .helpers import BACKEND, PASSWORD, make_user


class AuthenticationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        sync_roles()
        cls.user = make_user("demo", "Teacher")

    def test_custom_user_and_hashed_password(self):
        self.assertEqual(get_user_model()._meta.label, "accounts.User")
        self.assertNotEqual(self.user.password, PASSWORD)
        self.assertTrue(self.user.check_password(PASSWORD))

    def test_user_requires_email(self):
        with self.assertRaises(ValueError):
            get_user_model().objects.create_user("noemail", "", PASSWORD)

    def test_database_rejects_blank_email_outside_user_manager(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            get_user_model().objects.create(username="blank", email="")

    def test_admin_creation_requires_and_saves_custom_user_email(self):
        superuser = make_user("trusted", is_staff=True, is_superuser=True)
        self.client.force_login(superuser, backend=BACKEND)
        payload = {
            "username": "new-account",
            "usable_password": "true",
            "password1": PASSWORD,
            "password2": PASSWORD,
        }
        response = self.client.post("/admin/accounts/user/add/", payload)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(username="new-account").exists())
        payload["email"] = "new-account@example.invalid"
        response = self.client.post("/admin/accounts/user/add/", payload)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            get_user_model().objects.get(username="new-account").email,
            "new-account@example.invalid",
        )

    def test_superuser_creation(self):
        user = get_user_model().objects.create_superuser("root", "root@example.invalid", PASSWORD)
        self.assertTrue(user.is_superuser and user.is_staff)

    def test_email_is_case_insensitively_unique(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            get_user_model().objects.create_user("another", "DEMO@EXAMPLE.INVALID", PASSWORD)

    def test_login_cycles_session_and_records_event(self):
        session = self.client.session
        session["before_login"] = True
        session.save()
        previous_key = session.session_key
        response = self.client.post(
            reverse("accounts:login"), {"username": "demo", "password": PASSWORD}
        )
        self.assertRedirects(response, reverse("core:dashboard"), fetch_redirect_response=False)
        self.assertNotEqual(previous_key, self.client.session.session_key)
        self.assertTrue(AuditEvent.objects.filter(actor=self.user, event="auth.login").exists())

    def test_invalid_login_is_generic(self):
        response = self.client.post(
            reverse("accounts:login"), {"username": "demo", "password": "wrong"}
        )
        self.assertContains(response, "The username or password is incorrect.")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertTrue(AuditEvent.objects.filter(event="auth.login_failed").exists())

    def test_inactive_user_cannot_login(self):
        self.user.is_active = False
        self.user.save()
        response = self.client.post(
            reverse("accounts:login"), {"username": "demo", "password": PASSWORD}
        )
        self.assertContains(response, "The username or password is incorrect.")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_external_next_is_ignored(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "demo", "password": PASSWORD, "next": "https://example.org/phishing"},
        )
        self.assertEqual(response.url, reverse("core:dashboard"))

    def test_logout_requires_post_and_clears_session(self):
        self.client.force_login(self.user, backend=BACKEND)
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        response = self.client.post(reverse("accounts:logout"))
        self.assertRedirects(response, reverse("accounts:login"))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertTrue(AuditEvent.objects.filter(actor=self.user, event="auth.logout").exists())

    def test_csrf_on_login_and_logout(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(
            client.post(
                reverse("accounts:login"), {"username": "demo", "password": PASSWORD}
            ).status_code,
            403,
        )
        client.force_login(self.user, backend=BACKEND)
        self.assertEqual(client.post(reverse("accounts:logout")).status_code, 403)

    def test_login_rate_limit_blocks_even_valid_password(self):
        for _ in range(5):
            response = self.client.post(
                reverse("accounts:login"), {"username": "demo", "password": "wrong"}
            )
        self.assertEqual(response.status_code, 429)
        response = self.client.post(
            reverse("accounts:login"), {"username": "demo", "password": PASSWORD}
        )
        self.assertContains(response, "Please try again later", status_code=429)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_rate_limit_cannot_be_bypassed_using_forwarded_ip(self):
        for index in range(5):
            self.client.post(
                reverse("accounts:login"),
                {"username": f"unknown{index}", "password": "wrong"},
                HTTP_X_FORWARDED_FOR=f"192.0.2.{index}",
            )
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "demo", "password": PASSWORD},
            HTTP_X_FORWARDED_FOR="192.0.2.99",
        )
        self.assertEqual(response.status_code, 429)

    def test_password_reset_delivery_and_single_use(self):
        self.client.post(reverse("accounts:password_reset"), {"email": self.user.email})
        self.assertEqual(len(mail.outbox), 1)
        reset_url = re.search(r"http://testserver(/accounts/reset/\S+)", mail.outbox[0].body).group(
            1
        )
        response = self.client.get(reset_url)
        self.assertEqual(response.status_code, 302)
        final_url = response.url
        new_password = "Fictional-Changed-Passphrase-852!"
        response = self.client.post(
            final_url, {"new_password1": new_password, "new_password2": new_password}
        )
        self.assertRedirects(response, reverse("accounts:password_reset_complete"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(new_password))
        self.assertContains(self.client.get(reset_url), "This link has expired.")

    def test_password_reset_unknown_email_has_same_response(self):
        response = self.client.post(
            reverse("accounts:password_reset"), {"email": "unknown@example.invalid"}
        )
        self.assertRedirects(response, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

    def test_password_reset_rejects_weak_password(self):
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)
        response = self.client.get(reverse("accounts:password_reset_confirm", args=[uid, token]))
        response = self.client.post(response.url, {"new_password1": "123", "new_password2": "123"})
        self.assertContains(response, "too short")

    def test_all_role_routes_and_multiple_roles(self):
        for index, role in enumerate(ROLE_PERMISSIONS):
            with self.subTest(role=role):
                user = make_user(f"role{index}", role)
                self.client.force_login(user, backend=BACKEND)
                response = self.client.get(reverse("core:dashboard"))
                expected = {
                    "Teacher": "teacher",
                    "Student": "student",
                    "Parent or Guardian": "parent",
                }.get(role, "admin")
                self.assertRedirects(response, reverse("core:role_dashboard", args=[expected]))

    def test_anonymous_is_redirected(self):
        for url in ("/", "/students/", "/dashboard/admin/", "/modules/", "/audit/"):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 302)

    def test_user_without_role_is_denied_dashboard(self):
        self.client.force_login(make_user("unassigned"), backend=BACKEND)
        self.assertContains(self.client.get("/"), "No dashboard permissions", status_code=403)

    def test_wrong_dashboard_is_forbidden(self):
        self.client.force_login(self.user, backend=BACKEND)
        self.assertEqual(self.client.get("/dashboard/admin/").status_code, 403)
        self.assertEqual(self.client.get("/dashboard/unknown/").status_code, 404)

    def test_security_headers_and_private_cache(self):
        self.client.force_login(self.user, backend=BACKEND)
        response = self.client.get("/dashboard/teacher/")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertIn("script-src 'self'", response["Content-Security-Policy"])
