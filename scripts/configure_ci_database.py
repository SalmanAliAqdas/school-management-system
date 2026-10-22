"""Rotate the disposable GitHub-hosted PostgreSQL service's password for this run.

No Django settings or .env files are loaded. Connection targets are fixed to the
loopback CI service and a dedicated CI role/database, never a production URL.
"""

import os
import secrets
import sys
from pathlib import Path

import psycopg
from psycopg import sql


def configure_ci_database(environ, output):
    if (
        environ.get("GITHUB_ACTIONS") != "true"
        or environ.get("DJANGO_SETTINGS_MODULE") != "config.settings.test"
    ):
        raise ValueError("CI database setup requires GitHub Actions and test settings.")
    bootstrap = environ["CI_POSTGRES_BOOTSTRAP_PASSWORD"]
    port = int(environ["CI_POSTGRES_PORT"])
    if not bootstrap or not 1 <= port <= 65535:
        raise ValueError("Invalid CI database service configuration.")
    environment_file = Path(environ["GITHUB_ENV"])
    password = secrets.token_urlsafe(32)
    database_url = f"postgresql://schoolos_ci:{password}@127.0.0.1:{port}/schoolos_ci"
    print(f"::add-mask::{password}", file=output, flush=True)
    print(f"::add-mask::{database_url}", file=output, flush=True)
    with psycopg.connect(
        host="127.0.0.1",
        port=port,
        user="schoolos_ci",
        dbname="schoolos_ci",
        password=bootstrap,
        connect_timeout=5,
    ) as connection:
        connection.execute(
            sql.SQL("ALTER ROLE schoolos_ci PASSWORD {}").format(sql.Literal(password))
        )
    with environment_file.open("a", encoding="utf-8") as file:
        file.write(f"DATABASE_URL={database_url}\n")
    print("Isolated CI database credentials configured for this run.", file=output)


def main():
    try:
        configure_ci_database(os.environ, sys.stdout)
    except (KeyError, ValueError, OSError, psycopg.Error):
        raise SystemExit("Unable to configure the isolated CI database.") from None


if __name__ == "__main__":
    main()
