"""Create private PostgreSQL backups and rehearse restores into disposable databases."""

import argparse
import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from urllib.parse import unquote, urlparse

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def database():
    parsed = urlparse(os.environ["DATABASE_URL"])
    if parsed.scheme not in ("postgres", "postgresql") or not parsed.path.strip("/"):
        raise SystemExit("DATABASE_URL must identify PostgreSQL.")
    return parsed, unquote(parsed.path.strip("/"))


def executable(name, bin_dir):
    return str(Path(bin_dir, name + (".exe" if os.name == "nt" else ""))) if bin_dir else name


def environment(parsed):
    env = os.environ.copy()
    if parsed.password:
        env["PGPASSWORD"] = unquote(parsed.password)
    return env


def connection_args(parsed, name):
    args = ["--host", parsed.hostname or "localhost", "--port", str(parsed.port or 5432)]
    if parsed.username:
        args += ["--username", unquote(parsed.username)]
    return [*args, name]


def restore_connection_args(parsed, name):
    args = connection_args(parsed, name)
    return [*args[:-1], "--dbname", args[-1]]


def backup(parsed, source, bin_dir):
    directory = ROOT / ".local" / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"schoolos-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}.dump"
    subprocess.run(
        [
            executable("pg_dump", bin_dir),
            *connection_args(parsed, source),
            "--format=custom",
            "--file",
            str(target),
        ],
        check=True,
        env=environment(parsed),
    )
    if target.stat().st_size <= 0:
        raise SystemExit("Backup integrity check failed: empty output.")
    return target


def rehearse(parsed, source, target, bin_dir, keep):
    restored = "schoolos_restore_" + uuid.uuid4().hex[:12]
    if restored == source or not restored.startswith("schoolos_restore_"):
        raise SystemExit("Unsafe restore target.")
    started = time.perf_counter()
    env = environment(parsed)
    base = connection_args(parsed, restored)
    subprocess.run([executable("createdb", bin_dir), *base], check=True, env=env)
    try:
        subprocess.run(
            [
                executable("pg_restore", bin_dir),
                *restore_connection_args(parsed, restored),
                "--exit-on-error",
                "--no-owner",
                str(target),
            ],
            check=True,
            env=env,
        )
        restored_url = parsed._replace(path="/" + restored).geturl()
        with psycopg.connect(restored_url) as conn, conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM django_migrations")
            migrations = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM accounts_user")
            users = cursor.fetchone()[0]
            cursor.execute(
                """SELECT COUNT(*) FROM (SELECT journal_id FROM finance_journalline
                GROUP BY journal_id HAVING SUM(debit) <> SUM(credit)) invalid"""
            )
            unbalanced = cursor.fetchone()[0]
        if not migrations or unbalanced:
            raise SystemExit("Restored database integrity verification failed.")
        print(
            json.dumps(
                {
                    "restored_database": restored,
                    "migrations": migrations,
                    "users": users,
                    "unbalanced_journals": unbalanced,
                    "duration_seconds": round(time.perf_counter() - started, 3),
                }
            )
        )
    finally:
        if not keep:
            subprocess.run([executable("dropdb", bin_dir), *base], check=True, env=env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["backup", "rehearse"])
    parser.add_argument("--backup")
    parser.add_argument("--bin-dir", default="")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    parsed, source = database()
    target = Path(args.backup).resolve() if args.backup else backup(parsed, source, args.bin_dir)
    if ROOT not in target.parents or ".local" not in target.parts or not target.is_file():
        raise SystemExit("Backup must be an existing private file under .local.")
    print(f"Backup: {target} ({target.stat().st_size} bytes)")
    if args.action == "rehearse":
        rehearse(parsed, source, target, args.bin_dir, args.keep)


if __name__ == "__main__":
    main()
