"""Check tracked and untracked commit candidates without printing secret values."""

import argparse
import json
import math
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
SENSITIVE_DIRECTORIES = {
    ".local",
    "pgdata",
    "postgres_data",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "media",
    "uploads",
    "private_uploads",
    "private",
    "backups",
    "dumps",
    "exports",
    "logs",
    ".aws",
    ".ssh",
    ".secrets",
    "secrets",
    "credentials",
    "staticfiles",
}
SENSITIVE_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".sqlite",
    ".sqlite3",
    ".db",
    ".sql",
    ".dump",
    ".backup",
    ".log",
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".jks",
}
TOKEN_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "Stripe live key": re.compile(r"\b[rs]k_live_[A-Za-z0-9]{20,}\b"),
    "Slack token": re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{20,}\b"),
    "stored Django password hash": re.compile(r"\b(?:pbkdf2_sha256|argon2)\$[0-9a-zA-Z$+/=]{30,}"),
}
PUBLIC_FIXTURES = {
    "CHANGE_ME",
    "ci-only-ephemeral-password",
    "test-only-ephemeral-key-never-use-in-production-0123456789",
}


def git_paths(*args):
    result = subprocess.run(
        ["git", "ls-files", "-z", *args], cwd=ROOT, check=True, capture_output=True
    )
    return sorted(set(path.decode("utf-8") for path in result.stdout.split(b"\0") if path))


def sensitive_path(path):
    if path == ".env.example":
        return False
    pure = PurePosixPath(path.casefold())
    return (
        any(part in SENSITIVE_DIRECTORIES or part.startswith(".venv") for part in pure.parts)
        or pure.name.startswith(".env")
        or ".env" in pure.suffixes
        or pure.suffix in SENSITIVE_SUFFIXES
        or pure.name in {".netrc", "_netrc", ".pgpass", "pgpass.conf", ".pypirc", ".npmrc"}
        or pure.name.startswith(("id_rsa", "id_ed25519"))
        or (
            pure.suffix == ".json"
            and ("credentials" in pure.name or "service-account" in pure.name)
        )
    )


def entropy(value):
    return -sum((n / len(value)) * math.log2(n / len(value)) for n in Counter(value).values())


def local_private_values(check_identities):
    values = {}
    local_env = dotenv_values(ROOT / ".env")
    for name in ("SECRET_KEY", "DEMO_PASSWORD", "EMAIL_HOST_PASSWORD"):
        value = os.environ.get(name) or local_env.get(name)
        if value and value not in PUBLIC_FIXTURES and len(value) >= 8:
            values[f"local {name}"] = value
    database_url = os.environ.get("DATABASE_URL") or local_env.get("DATABASE_URL")
    if database_url:
        values["local database URL"] = database_url
        password = unquote(urlsplit(database_url).password or "")
        if len(password) >= 12 or (len(password) >= 6 and entropy(password) >= 3):
            values["local database credential"] = password
    if check_identities:
        sys.path.insert(0, str(ROOT))
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
        import django

        django.setup()
        from django.contrib.auth import get_user_model

        for number, email in enumerate(get_user_model().objects.values_list("email", flat=True)):
            if email and not email.casefold().endswith("@example.invalid"):
                values[f"local account email #{number + 1}"] = email
    return values


def check_repository(check_identities=False):
    candidates = git_paths("--cached", "--others", "--exclude-standard")
    tracked = git_paths("--cached")
    ignored_tracked = git_paths("--cached", "--ignored", "--exclude-standard")
    problems = [
        {"path": path, "issue": "ignored file is already tracked"} for path in ignored_tracked
    ]
    private_values = local_private_values(check_identities)
    example = dotenv_values(ROOT / ".env.example")
    for name in ("SECRET_KEY", "DEMO_PASSWORD", "EMAIL_HOST_PASSWORD", "EMAIL_HOST_USER"):
        if name not in example or example[name] not in {"", None, "CHANGE_ME"}:
            problems.append({"path": ".env.example", "issue": f"{name} must be a placeholder"})
    if urlsplit(example.get("DATABASE_URL") or "").password != "CHANGE_ME":
        problems.append({"path": ".env.example", "issue": "database password must be CHANGE_ME"})
    for path in candidates:
        if sensitive_path(path):
            problems.append({"path": path, "issue": "private/generated path is a commit candidate"})
        file = ROOT / path
        if file.is_symlink():
            problems.append({"path": path, "issue": "review symlink before committing"})
            continue
        if not file.is_file():
            continue
        content = file.read_bytes().decode("utf-8", errors="replace")
        for name, pattern in TOKEN_PATTERNS.items():
            for match in pattern.finditer(content):
                problems.append(
                    {"path": path, "line": content.count("\n", 0, match.start()) + 1, "issue": name}
                )
        for name, value in private_values.items():
            position = content.casefold().find(value.casefold())
            if position >= 0:
                problems.append(
                    {
                        "path": path,
                        "line": content.count("\n", 0, position) + 1,
                        "issue": f"matches {name}",
                    }
                )
    return {
        "tracked_files": len(tracked),
        "commit_candidates": len(candidates),
        "private_value_checks": len(private_values),
        "findings": problems,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-local-identities",
        action="store_true",
        help="Read local account emails to check they are absent from source.",
    )
    parser.add_argument("--report", type=Path, help="Write a sanitized report; no secret values.")
    args = parser.parse_args()
    result = check_repository(args.check_local_identities)
    if args.report:
        args.report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    raise SystemExit(bool(result["findings"]))


if __name__ == "__main__":
    main()
