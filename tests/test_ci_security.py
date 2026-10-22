import io
import json
import os
import secrets
import tempfile
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from django.conf import settings
from django.test import SimpleTestCase

from scripts.configure_ci_database import configure_ci_database
from scripts.repository_check import check_repository


class CIDatabaseSetupTests(SimpleTestCase):
    @patch("scripts.configure_ci_database.psycopg.connect")
    def test_setup_refuses_local_execution_and_production_settings(self, connect):
        for environment in (
            {"DJANGO_SETTINGS_MODULE": "config.settings.test"},
            {"GITHUB_ACTIONS": "true", "DJANGO_SETTINGS_MODULE": "config.settings.production"},
        ):
            with self.subTest(environment=environment), self.assertRaises(ValueError):
                configure_ci_database(environment, io.StringIO())
        connect.assert_not_called()

    @patch("scripts.configure_ci_database.psycopg.connect")
    def test_password_is_random_masked_and_limited_to_ci_service(self, connect):
        with tempfile.TemporaryDirectory() as directory:
            environment_file = Path(directory) / "github-env"
            environment = {
                "GITHUB_ACTIONS": "true",
                "DJANGO_SETTINGS_MODULE": "config.settings.test",
                "CI_POSTGRES_BOOTSTRAP_PASSWORD": secrets.token_urlsafe(24),
                "CI_POSTGRES_PORT": "5432",
                "GITHUB_ENV": str(environment_file),
                "DATABASE_URL": "postgresql://unrelated@example.invalid/production",
            }
            output = io.StringIO()
            configure_ci_database(environment, output)
            line = environment_file.read_text(encoding="utf-8").strip()
            self.assertTrue(line.startswith("DATABASE_URL="))
            url = urlsplit(line.split("=", 1)[1])
            self.assertEqual(url.hostname, "127.0.0.1")
            self.assertEqual(url.username, "schoolos_ci")
            self.assertEqual(url.path, "/schoolos_ci")
            self.assertGreaterEqual(len(url.password), 40)
            self.assertNotEqual(url.password, environment["CI_POSTGRES_BOOTSTRAP_PASSWORD"])
            self.assertIn(f"::add-mask::{url.password}", output.getvalue())
            self.assertIn(f"::add-mask::{url.geturl()}", output.getvalue())
            self.assertEqual(connect.call_args.kwargs["host"], "127.0.0.1")
            self.assertEqual(connect.call_args.kwargs["user"], "schoolos_ci")
            self.assertEqual(connect.call_args.kwargs["dbname"], "schoolos_ci")
            self.assertEqual(
                connect.call_args.kwargs["password"],
                environment["CI_POSTGRES_BOOTSTRAP_PASSWORD"],
            )
            connect.return_value.__enter__.return_value.execute.assert_called_once()
            output = io.StringIO()
            configure_ci_database(environment, output)
            second_line = environment_file.read_text(encoding="utf-8").splitlines()[1]
            self.assertNotEqual(line, second_line)


class CISecretScannerTests(SimpleTestCase):
    def scan_source(self, password, *, leaked):
        database_url = f"postgresql://schoolos_ci:{password}@127.0.0.1:5432/schoolos_ci"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env.example").write_text(
                (settings.BASE_DIR / ".env.example").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            (root / "settings.py").write_text(
                f"DATABASE_URL = {database_url!r}\n" if leaked else "# No credentials in source.\n",
                encoding="utf-8",
            )
            with (
                patch("scripts.repository_check.ROOT", root),
                patch(
                    "scripts.repository_check.git_paths",
                    side_effect=[
                        ["settings.py"],
                        ["settings.py"],
                        [],
                    ],
                ),
                patch.dict(
                    os.environ,
                    {
                        "GITHUB_ACTIONS": "true",
                        "DATABASE_URL": database_url,
                    },
                    clear=True,
                ),
            ):
                return check_repository()

    def test_runtime_ci_credentials_are_not_findings_when_absent_from_source(self):
        self.assertEqual(self.scan_source(secrets.token_urlsafe(32), leaked=False)["findings"], [])

    def test_actual_ci_database_credentials_in_source_still_fail(self):
        password = secrets.token_urlsafe(32)
        report = self.scan_source(password, leaked=True)
        self.assertEqual(
            {item["issue"] for item in report["findings"]},
            {
                "matches local database URL",
                "matches local database credential",
            },
        )
        self.assertNotIn(password, json.dumps(report))

    def test_old_public_fixture_is_not_a_database_credential_exemption(self):
        password = "ci-only-" + "ephemeral-password"
        report = self.scan_source(password, leaked=True)
        self.assertEqual(len(report["findings"]), 2)
