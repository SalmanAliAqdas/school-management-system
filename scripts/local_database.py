"""Run an isolated, loopback-only PostgreSQL cluster for local development.

Requires official PostgreSQL Windows binaries in .local/postgresql/pgsql/bin,
or --bin-dir pointing to an existing PostgreSQL bin directory. No installation,
Windows service, machine configuration, or application deployment is performed.
"""

import argparse
import os
import secrets
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local"


def run(binary_dir, command, *args, env=None):
    # A server can inherit pipe handles from pg_ctl on Windows. Capture to a file
    # so the parent waits only for pg_ctl, not for the long-running server.
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as output:
        result = subprocess.run(
            [str(binary_dir / f"{command}.exe"), *map(str, args)],
            stdout=output,
            stderr=output,
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        output.seek(0)
        print(output.read(), end="")
    result.check_returncode()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bin-dir", type=Path, default=LOCAL / "postgresql" / "pgsql" / "bin")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--port", type=int, default=55432)
    args = parser.parse_args()
    binary_dir = args.bin_dir.resolve()
    data = LOCAL / "pgdata"
    if not (binary_dir / "pg_ctl.exe").is_file():
        parser.error("PostgreSQL binaries were not found. Supply --bin-dir.")
    if args.stop:
        run(binary_dir, "pg_ctl", "-D", data, "-m", "fast", "-w", "stop")
        return
    LOCAL.mkdir(exist_ok=True)
    password_file = LOCAL / "db-password"
    if not (data / "PG_VERSION").exists():
        password = secrets.token_urlsafe(36)
        password_file.write_text(password, encoding="utf-8")
        run(
            binary_dir,
            "initdb",
            "-D",
            data,
            "-U",
            "schoolos",
            "--pwfile",
            password_file,
            "--auth=scram-sha-256",
            "--encoding=UTF8",
            "--locale=C",
        )
    password = password_file.read_text(encoding="utf-8").strip()
    if not (data / "postmaster.pid").exists():
        run(
            binary_dir,
            "pg_ctl",
            "-D",
            data,
            "-l",
            LOCAL / "postgresql.log",
            "-o",
            f"-h 127.0.0.1 -p {args.port}",
            "-w",
            "start",
        )
    import psycopg

    with psycopg.connect(
        host="127.0.0.1",
        port=args.port,
        user="schoolos",
        password=password,
        dbname="postgres",
        autocommit=True,
        connect_timeout=5,
    ) as connection:
        if not connection.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", ("schoolos",)
        ).fetchone():
            connection.execute("CREATE DATABASE schoolos")
    env_file = ROOT / ".env"
    if not env_file.exists():
        env_file.write_text(
            "DJANGO_SETTINGS_MODULE=config.settings.development\n"
            f"SECRET_KEY={secrets.token_urlsafe(64)}\nDJANGO_DEBUG=True\n"
            f"DATABASE_URL=postgresql://schoolos:{quote(password)}@127.0.0.1:{args.port}/schoolos\n"
            "ALLOWED_HOSTS=localhost,127.0.0.1\nTIME_ZONE=Asia/Karachi\n"
            "ALLOW_DEMO_DATA=False\nDEMO_PASSWORD=\n",
            encoding="utf-8",
        )
        print("Created ignored .env with random local secrets; demo data remains disabled.")
    print(f"Local PostgreSQL ready on 127.0.0.1:{args.port}. Existing .env files are preserved.")


if __name__ == "__main__":
    main()
