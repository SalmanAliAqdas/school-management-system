# Phase 1 verification and repository security review

Reviewed on 22 October 2026.

**Decision: the reviewed Phase 1 source files are safe to commit and ready for
GitHub.** Private configuration, credentials, database files and uploads remain
excluded. No files were staged, committed or pushed during this review.

## Verification results

| Area | Result |
| --- | --- |
| Django system checks, including database configuration | Passed; no issues |
| Production deployment settings checks | Passed; no issues |
| Existing database migrations | All 35 applied, including seven first-party migration files |
| Unapplied migrations and model drift | None; migrate --check and makemigrations --check passed |
| Automated tests | 72 passed in a uniquely named disposable PostgreSQL database |
| Independent installation | Fresh source copy, fresh virtual environment, separate PostgreSQL database; setup and all 72 tests passed |
| Authentication and access | Login, POST logout, reset tokens, CSRF, rate limiting, eleven roles and object restrictions passed |
| Browser verification | Four role dashboards, charts, student search/detail, sidebar links, logout and mobile menu passed in Chrome |
| PostgreSQL | Real PostgreSQL 17.11 through psycopg; no SQLite fallback |
| Production static collection | Compressed/manifest-hashed files generated successfully |
| Ruff lint and format; pip dependency compatibility | Passed |
| Tracked and untracked source secret scan | Gitleaks 8.30.1: zero findings in the complete commit-candidate export |
| Local-secret and account-email comparison | Zero matches in commit candidates; values never printed in reports |
| Python dependency advisory scan | pip-audit 2.10.1: no known vulnerabilities after installer update |
| Browser dependency advisory scan | OSV: no advisories for Bootstrap 5.3.8 or Chart.js 4.5.1 |
| Existing database and administrator preservation | Account password/privilege fingerprints and every application table row count unchanged |

Tests used separately named databases rather than the application database. The
clean-install check created its own fictional superuser and demonstration records;
it did not alter the existing administrator. The temporary browser server used
port 8011 and was stopped afterward. Existing application services were left alone.

## Problems fixed

1. Expanded `.gitignore` to cover common virtual environments, environment-file
   variants, PostgreSQL data directories, private uploads, exports, logs, dumps,
   backups, private keys and credential stores. No ignored files were already tracked.
2. Added `.gitattributes` to keep text files, including the Linux build script,
   checked out with LF line endings across Windows and Linux.
3. Corrected `manage.py` to load `.env` before selecting the settings module. An
   explicitly exported module still takes precedence. A regression test verifies
   that choosing production in an environment file actually loads production.
4. Updated the local pip installer from 25.1.1 to 26.2.2 after the advisory scan
   found published installer vulnerabilities. Application packages had no reported
   advisories. README, CI and build steps now upgrade pip before installing packages.
5. Added a repeatable, sanitized repository check and CI invocation. Regression
   tests verify ignore rules, public template inclusion, placeholder credentials,
   private-file rejection and provider-token detection.
6. Made browser verification configurable for a separate local preview, validating
   the parsed hostname and rejecting credential-bearing or external URLs.
7. Clarified README prerequisites, PostgreSQL binary availability, safe `.env`
   creation, migration checks, security checks and public fictional test fixtures.

`requirements.txt` successfully installed the application into a new environment
and required no application dependency changes. Optional browser tooling remains
separate. `.env.example` contains public configuration defaults, empty credential
fields and `CHANGE_ME` as the database-password placeholder.

## Safe first-commit contents

The exact reviewed source list is [FILE_MANIFEST.md](FILE_MANIFEST.md). It includes:

- `.env.example`, `.gitattributes`, `.gitignore`, `.python-version` and `.github/`.
- `manage.py`, `config/`, `accounts/`, `academics/`, `people/`, `core/` and `audit/`,
  including every initial migration.
- `templates/`, `static/` and vendored dependency licenses/source maps.
- `tests/`, `scripts/`, `requirements*.txt`, `pyproject.toml`, `build.sh` and `render.yaml`.
- `README.md`, `IMPLEMENTATION_STATUS.md` and `docs/`.

At review time these files are untracked because the main repository has no first
commit. There are no tracked private files and no commit history requiring cleanup.
The normal first-commit candidate set excludes all private/runtime material.

## Keep out of Git

Do not add `.env` or other real environment files, `.venv/`, `.local/`, PostgreSQL
data, caches, `staticfiles/`, `media/`, uploads, logs, exports, backups, database dumps,
private keys or credentials. The review tool environments, clean-install copy,
generated test credentials, database fingerprints, logs, detailed scanner reports
and screenshots are all under ignored `.local/phase1-review/`.

Fictional passwords in test fixtures, the test-only Django secret and the ephemeral
CI PostgreSQL service password are intentional public test data. No matching
production/default account is provisioned from these values. Actual local secrets
and the administrator's email were compared against source without printing them.

## Repeatable checks

```powershell
.\.venv\Scripts\python.exe manage.py check --database default
.\.venv\Scripts\python.exe manage.py check --deploy --settings=config.settings.production
.\.venv\Scripts\python.exe manage.py migrate --check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test tests --settings=config.settings.test --noinput
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe scripts/repository_check.py --check-local-identities
git status --short
```

The identity-aware check is local-only and needs database access. CI uses the
database-independent variant. Detailed local review evidence is intentionally not
part of the commit. Secret scans and vulnerability results apply to this reviewed
snapshot and advisory data available at review time; rerun them for later changes.

GitHub CI itself, real SMTP delivery and Render deployment have not been run.
Production operation still requires the validation described in [SECURITY.md](SECURITY.md).
