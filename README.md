# RumiWare SchoolOS

A modular school management application built with Django, PostgreSQL and
server-rendered templates. School administration, admissions and academic operations
are implemented on the existing foundation. Local demonstrations use fictional data.

## Foundation capabilities

- Custom user model from the first migration; eleven permission groups and multiple roles.
- Sign-in, POST sign-out, database-backed login throttling and email password resets.
- Administration, teacher, student and guardian dashboard shells.
- Permission-scoped student directory, profile reads and enrollment history.
- Explicit guardian links and teacher section/year/subject assignments.
- School identity settings, account information and a read-only audit trail.
- Responsive local-asset design system, accessible forms and real enrollment charts.
- PostgreSQL migrations, automated tests, Ruff, CI and Render deployment configuration.

Academic setup, admissions, enrollment transitions, guardian management, staff
profiles, safe private images, CSV preview/confirmation and printable records now
have dedicated interfaces. See the [school operations guide](docs/SCHOOL_OPERATIONS.md)
for setup, permissions, academic lifecycle, import columns and historical protections.
Attendance now includes student/staff registers, calendars, corrections, leave,
guardian notices, dashboards and scoped CSV/PDF reports. See the
[attendance operating and policy guide](docs/ATTENDANCE_POLICY.md).
Examinations now include weighted assessments, configurable grading, date sheets,
scoped marks entry, independent review, publication snapshots, corrections, student/
guardian portals, analytics and branded PDF report cards. See the
[examination and grading policy](docs/EXAMINATION_POLICY.md).
Fees and finance now include dated fee structures, concessions, safe billing previews,
independent approvals, manual collections, immutable receipts, balanced journals,
refunds/reversals, expenses, reconciliation, reports and basic family fee access.
See the [finance operating policy](docs/FINANCE_POLICY.md) and `/finance/`.
Later phases remain planned; no real banking or payment gateway is connected.

## Requirements

- Python 3.12–3.14; local verification used Python 3.13.
- PostgreSQL 14 or newer; PostgreSQL 17 is the verification/CI baseline.
- Windows PowerShell and Git. VS Code is supported without additional extensions.

Node.js, frontend compilation, Redis, Celery and Docker are not required for local
development. CI uses a hosted PostgreSQL service container, not a local Docker setup.

## Local setup (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade "pip>=26.2"
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
if (-not (Test-Path -LiteralPath .env)) { Copy-Item .env.example .env }
```

Create a dedicated PostgreSQL login and database using an existing administrator
connection. `psql` may require its full installed path on Windows.

```sql
CREATE ROLE schoolos LOGIN CREATEDB;
\password schoolos
CREATE DATABASE schoolos OWNER schoolos;
```

`CREATEDB` is needed for Django's test database and should not be granted to the
production application role. Set `DATABASE_URL` in `.env` with this login's password;
URL-encode reserved password characters. Generate a local secret:

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(64))"
```

Set the result as `SECRET_KEY` in `.env`. Keep the file untracked. Then initialize
and serve the application:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py sync_roles
.\.venv\Scripts\python.exe manage.py createsuperuser
.\.venv\Scripts\python.exe manage.py runserver
```

Open **http://127.0.0.1:8000/**. The trusted system interface is `/admin/`; the
database readiness endpoint is `/health/`. New ordinary users need an explicitly
assigned group and, where applicable, a linked people profile. Application System
Administrator group membership does not grant Django superuser status.

### Optional isolated PostgreSQL cluster

The Windows helper can use official PostgreSQL binaries without registering a
service or changing machine configuration:

```powershell
.\.venv\Scripts\python.exe scripts/local_database.py --bin-dir 'C:\path\to\pgsql\bin'
```

It initializes `.local/pgdata`, binds only `127.0.0.1:55432`, generates a random
development database password, and creates `.env` **only if it does not exist**.
An existing `.env` must be configured to match the chosen database. The default
binary directory is `.local/postgresql/pgsql/bin`. PostgreSQL binaries and data
are excluded from the repository and must be provided on each development computer.

```powershell
.\.venv\Scripts\python.exe scripts/local_database.py --bin-dir 'C:\path\to\pgsql\bin' --stop
```

All binaries, runtime data, passwords and `.env` are ignored. This cluster's
database login is a local cluster administrator and must never be reused remotely.

## Fictional demonstration data

Demo initialization is explicit and is refused outside development. In the local
`.env`, set `DJANGO_DEBUG=True`, `ALLOW_DEMO_DATA=True` and a unique `DEMO_PASSWORD` meeting
the 12-character password policy. No default password is included in source.

```powershell
.\.venv\Scripts\python.exe manage.py seed_demo
```

The command creates eleven fictional accounts, six students, one guardian link,
three sections, academic dates, teacher assignments and school settings. It is
transactional and repeatable, preserving existing account passwords and records.
Demo accounts are ordinary users; none receives Django staff or superuser flags.

| Username | Role |
| --- | --- |
| `demo.admin` | System Administrator |
| `demo.principal` | Principal |
| `demo.schooladmin` | School Administrator |
| `demo.accountant` | Accountant |
| `demo.exams` | Examination Controller |
| `demo.teacher` | Teacher |
| `demo.student` | Student |
| `demo.parent` | Parent or Guardian |
| `demo.hr` | HR Manager |
| `demo.librarian` | Librarian |
| `demo.transport` | Transport Manager |

All initially created demo accounts use the locally supplied `DEMO_PASSWORD`.
Account email addresses use the reserved `example.invalid` domain. Enabling the
demo flag displays a fictional-data notice. It does not initialize any data by
itself. Existing non-demo accounts with colliding usernames cause the seed to stop.

## Checks and tests

All tests run on PostgreSQL; there is no silent SQLite fallback.

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py migrate --check
.\.venv\Scripts\python.exe manage.py test tests --settings=config.settings.test --noinput
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe scripts/repository_check.py
```

Test settings use a fast hasher exclusively for test fixtures. Development and
production retain Django's normal password hashing. Test fixture credentials are
fictional and never provision production users. CI runs the same checks on PostgreSQL
17. [Verification evidence](docs/VERIFICATION.md) records the executed checks.

## Repository security

`.env.example` contains public configuration defaults, empty secret fields and a
`CHANGE_ME` database password. Real environment files, virtual environments,
Python caches, private uploads, database dumps, logs, backups and credential stores
are excluded by `.gitignore`. Never force-add these files. Fictional test passwords
are public fixtures and never production defaults. CI rotates its isolated database
password to a random value for each run and masks it in logs; see [CI security](docs/CI.md).

`scripts/repository_check.py` checks tracked and untracked commit candidates and
rejects private/generated paths, common provider tokens, private keys, stored password
hashes and copies of known local secrets. Optional `--check-local-identities` also
reads local account emails to ensure they do not appear in source. Reports contain
file/line references and finding types, never matched secret values. This targeted
check complements a full secret scanner and dependency advisory review.

Fresh Python installations can include an older bundled pip; the setup and build
commands update it to a fixed release before installing dependencies. The reviewed
Phase 1 commit boundaries and results are in [the repository review](docs/REPOSITORY_REVIEW.md).

## Configuration and deployment

`config/settings/` separates development, test and production configuration.
`manage.py` loads `.env` before choosing the settings module; an explicitly exported
`DJANGO_SETTINGS_MODULE` takes precedence. WSGI/ASGI default to production settings.
`DATABASE_URL` is mandatory. `TIME_ZONE` defaults to `Asia/Karachi`; school settings
store a separate timezone/currency boundary for future workflows. Attendance and examination workflows
use the configured school timezone; other UI dates use the environment timezone. Bootstrap 5.3.8 and Chart.js 4.5.1 are vendored.

Development password reset emails print to the server console. Production uses
SMTP environment settings from `.env.example`; validate actual delivery before
provisioning real accounts. Reset requests for unknown addresses return the same
message. Authorized profile/logo forms accept sanitized PNG/JPEG images. Image
delivery uses authenticated, scoped routes; there is no public media-serving endpoint.

`render.yaml` describes a Python web service and PostgreSQL database. `build.sh`
installs dependencies and collects static assets; the pre-deploy command applies
migrations and synchronizes roles. Gunicorn is used on Render/Linux. Render plans
and pre-deploy commands may incur charges. This repository does not trigger a
deployment; authorization and service configuration are separate operational steps.

Before an authorized deployment, set allowed hosts/custom domains, trusted CSRF
origins, email credentials, and a random production key. Enable forwarded HTTPS
trust only for a verified stripping proxy. Review HSTS for the selected domain,
database SSL requirements and production permissions. Run:

```powershell
.\.venv\Scripts\python.exe manage.py check --deploy --settings=config.settings.production
```

Review [security limits](docs/SECURITY.md), including proxy-aware throttling, private
file storage, reset abuse prevention, retention and audit immutability. An actual
Render deployment, SMTP delivery and commercial readiness have not been established
by local checks.

## Project layout

```text
accounts/        custom users, role groups, auth and demo commands
academics/       academic years, terms, classes, sections, subjects, assignments
people/          admissions, profiles, guardians, enrollment history, imports and scoped reads
core/            school settings, dashboards, design system, readiness
audit/           security and access events
attendance/      student/staff attendance, leave, calendars, notices and reports
examinations/    assessment setup, marks, grading, publication and report cards
config/          Django configuration and server entry points
templates/       shared layouts, auth pages and role workspaces
static/          local CSS, JavaScript, brand mark and vendor assets
tests/           authentication, authorization and database regression tests
scripts/         optional isolated local database helper
docs/            architecture, database, permissions, security and verification
```

See [architecture and phased plan](docs/ARCHITECTURE.md), [database design](docs/DATABASE.md),
[permission matrix](docs/PERMISSIONS.md) and [implementation status](IMPLEMENTATION_STATUS.md).
The [file manifest](docs/FILE_MANIFEST.md) lists all source files created for this foundation.
