import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class ConfigurationTests(SimpleTestCase):
    def load_settings(self, module, **overrides):
        env = os.environ.copy()
        env.update(
            {
                "DJANGO_SETTINGS_MODULE": module,
                "SECRET_KEY": "a" * 64,
                "DJANGO_DEBUG": "True",
                "ALLOW_DEMO_DATA": "True",
            }
        )
        env.update(overrides)
        return subprocess.run(
            [
                sys.executable,
                "-c",
                "from django.conf import settings; print(settings.DEBUG, settings.ALLOW_DEMO_DATA)",
            ],
            cwd=settings.BASE_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )

    def test_production_cannot_enable_debug_or_demo(self):
        result = self.load_settings("config.settings.production")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "False False")

    def test_production_rejects_missing_secret(self):
        result = self.load_settings("config.settings.production", SECRET_KEY="")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Production SECRET_KEY", result.stderr)

    def test_database_url_is_required(self):
        result = self.load_settings("config.settings.development", DATABASE_URL="")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DATABASE_URL must point", result.stderr)

    def test_sqlite_cannot_silently_replace_postgresql(self):
        result = self.load_settings(
            "config.settings.development", DATABASE_URL="sqlite:///:memory:"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires PostgreSQL", result.stderr)

    def test_unrelated_debug_environment_does_not_disable_development(self):
        result = self.load_settings("config.settings.development", DEBUG="release")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "True True")

    def test_manage_honors_settings_module_from_environment_file(self):
        env = os.environ.copy()
        env.pop("DJANGO_SETTINGS_MODULE", None)
        env["PYTHONPATH"] = str(settings.BASE_DIR)
        env["SECRET_KEY"] = secrets.token_urlsafe(64)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copyfile(settings.BASE_DIR / "manage.py", root / "manage.py")
            (root / ".env").write_text(
                "DJANGO_SETTINGS_MODULE=config.settings.production\n", encoding="utf-8"
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(root / "manage.py"),
                    "check",
                    "--deploy",
                    "--fail-level",
                    "WARNING",
                ],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
