# Phase 1 continuous integration

The `Foundation checks` workflow runs on pushes and pull requests. It uses a
GitHub-hosted Ubuntu runner, Python 3.13 and a disposable PostgreSQL 17 service.
It needs no repository secrets, production credentials or production services.

## Database isolation and credentials

The service publishes PostgreSQL only on runner loopback and uses the dedicated
`schoolos_ci` role and database. Its initial bootstrap password is derived from
the run ID and attempt, so there is no shared password literal in source.

After installing dependencies, `scripts/configure_ci_database.py` replaces that
bootstrap password with a cryptographically random password. It masks the password
and connection URL in Actions logs, then exports DATABASE_URL through GITHUB_ENV
for subsequent steps. The runtime credentials are never written into a source
file or `.env`. They exist only for the disposable service's lifetime.

The helper requires GitHub Actions plus `config.settings.test`. It never loads
local `.env` files and fixes the connection target to `127.0.0.1`, `schoolos_ci`
and the mapped service port. An existing DATABASE_URL is not used to select a
connection target. No production resource or local administrator is provisioned,
modified or authenticated by this setup. The service is removed when the job ends.

## Repository scanner behavior

The repository scanner runs normally with the generated DATABASE_URL. There is
no CI bypass, ignored workflow path, database-secret exception or reduced token
detection. Actual runtime credentials copied into source still fail the check.

The initial workflow used a public test-database password in both its service
configuration and DATABASE_URL. The scanner matched that runtime value in the
workflow and its own public-fixture list, producing three false positives in
[the initial failed run](https://github.com/SalmanAliAqdas/school-management-system/actions/runs/39710348087).
Runtime generation removes those literal matches while retaining detection of
genuine database credentials, including when GITHUB_ACTIONS is set.

Regression tests cover setup refusal outside CI or under production settings,
random password rotation and masking, fixed connection targets, leak-free runtime
credentials, real leaked database credentials and the former public fixture.

## Checks

The workflow performs the repository scan, Ruff lint/format, Django system checks,
migration drift checks, migration application/checking and all automated tests.
Local CI-fix validation passed 77 tests in a separately named test database; the
existing application database and account password/privilege fingerprints were
preserved. Workflow expressions were also checked with actionlint.

For local verification, use the checks in [README.md](../README.md). Do not execute
the CI database setup helper against a development database. Current remote run
results are available on the repository's Actions tab.

## Attendance phase

The same PostgreSQL workflow now validates the Phase 3 attendance migrations and
full regression suite, including concurrent register/correction writes and database
record guards. ReportLab is installed from the normal requirements for PDF tests.
No external messaging/deployment credentials are needed. Browser workflow QA remains
an optional local check using installed Chrome and an isolated temporary database;
see ATTENDANCE_POLICY.md. GitHub Actions is verified against the pushed commit.
