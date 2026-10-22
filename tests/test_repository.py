import subprocess
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase
from dotenv import dotenv_values

from scripts.browser_smoke import preview_base_url
from scripts.repository_check import TOKEN_PATTERNS, sensitive_path


class RepositoryBoundaryTests(SimpleTestCase):
    def test_private_paths_are_ignored_by_git(self):
        paths = [
            ".env",
            ".env.production",
            ".env.backup",
            ".envrc",
            "production.env",
            "settings.env.local",
            ".venv/Scripts/python.exe",
            ".venv-review/pyvenv.cfg",
            "venv/pyvenv.cfg",
            "env/pyvenv.cfg",
            "accounts/__pycache__/models.pyc",
            ".local/db-password",
            "pgdata/PG_VERSION",
            "postgres_data/postgresql.conf",
            "media/private/student.pdf",
            "uploads/student.pdf",
            "private_uploads/student.pdf",
            "private/record.pdf",
            "backups/school.dump",
            "dumps/school.sql",
            "exports/students.csv",
            "logs/server.log",
            "server.log.1",
            "db.sqlite3",
            "school.db",
            "school.sql",
            "school.dump",
            ".aws/credentials",
            ".ssh/id_ed25519",
            "credentials/account.json",
            ".netrc",
            ".pgpass",
            "server.pem",
            "server.key",
            "account.p12",
            "service-account.json",
        ]
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "--stdin", "-z"],
            input=("\0".join(paths) + "\0").encode(),
            capture_output=True,
            cwd=settings.BASE_DIR,
            check=True,
        )
        self.assertEqual(set(result.stdout.decode().rstrip("\0").split("\0")), set(paths))

    def test_public_source_and_example_are_not_ignored(self):
        paths = [
            ".env.example",
            "README.md",
            "accounts/models.py",
            "tests/helpers.py",
            "static/vendor/bootstrap.LICENSE",
        ]
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "--stdin", "-z"],
            input=("\0".join(paths) + "\0").encode(),
            capture_output=True,
            cwd=settings.BASE_DIR,
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")

    def test_environment_template_has_only_placeholder_credentials(self):
        values = dotenv_values(Path(settings.BASE_DIR) / ".env.example")
        for name in ("SECRET_KEY", "DEMO_PASSWORD", "EMAIL_HOST_PASSWORD", "EMAIL_HOST_USER"):
            with self.subTest(name=name):
                self.assertEqual(values[name], "")
        self.assertIn(":CHANGE_ME@", values["DATABASE_URL"])
        self.assertEqual(values["ALLOW_DEMO_DATA"], "False")

    def test_sensitive_paths_are_rejected_even_if_force_added(self):
        for path in (
            ".env",
            "media/student.pdf",
            "config/production.env",
            "venv/config",
            "keys/server.key",
            "backups/data.sql",
            "secrets/service.json",
        ):
            with self.subTest(path=path):
                self.assertTrue(sensitive_path(path))
        self.assertFalse(sensitive_path(".env.example"))
        self.assertFalse(sensitive_path("tests/test_authentication.py"))

    def test_scanner_detects_provider_tokens_without_real_test_credentials(self):
        token = "ghp_" + "x" * 36
        self.assertIsNotNone(TOKEN_PATTERNS["GitHub token"].search(token))
        key = "-----BEGIN " + "PRIVATE KEY-----"
        self.assertIsNotNone(TOKEN_PATTERNS["private key"].search(key))

    def test_browser_tool_cannot_send_demo_credentials_to_remote_hosts(self):
        self.assertEqual(preview_base_url("http://localhost:8011/"), "http://localhost:8011")
        for url in (
            "https://example.org",
            "http://127.0.0.1:8000@example.org",
            "http://localhost:8000/path",
            "http://localhost:8000?target=example.org",
            "http://example.org:8000",
            "http://localhost:invalid",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                preview_base_url(url)
