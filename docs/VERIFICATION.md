# Foundation verification

Executed locally on 22 October 2026 with Python 3.13.5, Django 5.2.18,
PostgreSQL 17.11 and psycopg 3.3.6. The database was an isolated, password-protected
cluster bound to `127.0.0.1:55432`; SQLite was not used.

## Commands and results

| Check | Result |
| --- | --- |
| `python manage.py check` | No issues |
| `python manage.py check --deploy --settings=config.settings.production` | No issues |
| `python manage.py makemigrations --check --dry-run` | No changes detected |
| `python manage.py migrate --noinput` | All migrations applied |
| `python manage.py sync_roles` | Eleven roles initialized; idempotence tested |
| `python manage.py test tests --settings=config.settings.test --noinput` | 72 tests passed, also on a clean installation |
| `python -m ruff check .` | Passed |
| `python -m ruff format --check .` | Passed |
| `python -m pip check` | No broken requirements |
| `python manage.py collectstatic --noinput --settings=config.settings.production` | Passed, compressed/hashed assets generated |
| `python manage.py seed_demo` | Explicit local demo initialized; repeatability covered in tests |
| `python scripts/browser_smoke.py` | Passed with installed headless Chrome |
| Production-settings Django request smoke | Login, hashed static asset and database health returned 200; security headers present |
| `git check-ignore .env .local .venv staticfiles` | All generated/private paths ignored |
| Source and dependency security review | Passed; see REPOSITORY_REVIEW.md |

## First-party migrations executed

- `accounts.0001_initial`: custom User before dependent application tables.
- `accounts.0002_user_user_email_not_blank`: database email presence constraint.
- `core.0001_initial`: singleton school settings.
- `academics.0001_initial`: academic structure and initial assignment model.
- `people.0001_initial`: independent profiles, explicit guardian links and history.
- `academics.0002_initial`: teacher reference and academic cross-app constraints.
- `audit.0001_initial`: indexed audit events.

The two academics migrations resolve the teacher/profile dependency cycle without
moving the custom User out of its initial migration. Django authentication, admin,
sessions, content types and django-axes migrations also applied successfully.

## Test coverage

Authentication tests exercise user/superuser creation, required and unique emails,
admin provisioning, password hashing, successful/failed/inactive sign-in, session
rotation, safe redirects, POST logout, CSRF, database-backed lockout, spoofed
forwarded-IP denial, reset delivery, weak-password rejection and single-use tokens.

Access tests cover all eleven role routes, multiple roles, wrong dashboards, anonymous
and unassigned accounts, student isolation, explicit guardian links, teacher section
and year restrictions, restricted history, link revocation, search scope, account
deactivation, staff/admin isolation and denied accountant access. No mark workflow
exists; tests verify the accountant has no mark-change permission.

Database tests exercise date/current-year/placement/link/singleton constraints,
protected deletion, historical transfers, overlap validation, profile/audit retention,
school setting validation, audit permissions, private-PDF boundaries and demo guards.
Configuration subprocess tests reject missing secrets/database URLs and SQLite,
force production debug/demo off, and verify the DJANGO_DEBUG environment boundary.
Additional repository tests verify private-file exclusion, the placeholder-only
template, scanner detection and loopback-only browser credentials. A startup
regression test verifies that manage.py honors a settings module selected in `.env`.

## Browser checks and artifacts

Headless Chrome verified real form sign-in and POST sign-out for administration,
teacher, student and guardian accounts. It confirmed chart instantiation from saved
data, working sidebar links, filtered student search, record navigation, no horizontal
page overflow at 390px, inert hidden navigation, keyboard Escape behavior and no
JavaScript/console errors. Screenshots were inspected at desktop and mobile sizes:

- `.local/previews/login-desktop.png`
- `.local/previews/dashboard-desktop.png`
- `.local/previews/login-mobile.png`
- `.local/previews/dashboard-mobile.png`

Optional reproduction requires `requirements-browser.txt`, installed Chrome, an
explicitly seeded local demo and a running development server on port 8000. Automated
browser checks are smoke coverage, not a full accessibility certification.

The final preview used the explicit local demo flag and visibly labeled its fictional
records. A production-settings Django client also exercised login rendering, a
manifest-hashed CSS response and the database health check; this did not launch a
production server or deploy an application.

## Resolved verification findings

Production static collection initially rejected referenced vendor source maps; the
version-matched maps and complete license texts are now vendored. An inherited
generic DEBUG environment variable interfered with local settings; the dedicated
DJANGO_DEBUG variable and a regression test resolve that collision. The Windows
database helper now captures pg_ctl output without waiting on inherited server pipes.

## Limits

No actual Render deployment, GitHub CI run, real SMTP delivery, malware scanning,
restore drill, penetration test or load test was performed. Render configuration
was checked against its official configuration documentation and remains an
undeployed template. Local checks do not establish commercial readiness.
The subsequent repository review used separate test/installation databases,
preserving the running application and existing administrator. Its temporary
preview was stopped; see [the review report](REPOSITORY_REVIEW.md).

References: [Django supported versions](https://www.djangoproject.com/download/),
[Django deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/),
[Render Blueprint reference](https://render.com/docs/blueprint-spec),
[Render Python versions](https://render.com/docs/python-version).


## School operations verification - 22 October 2026

This section supersedes the foundation-only module boundary above.

- Six new first-party migrations applied successfully to the existing local PostgreSQL
  database, including btree_gist, overlap/uniqueness constraints, legacy backfills,
  immutable placement guards and active roll corrections. No migrations remain pending.
- Full automated suite: **130 tests passed** on PostgreSQL, zero failures/errors.
  This includes all original 77 authentication/configuration/dashboard/scope tests.
- New coverage: role/service denials, CSRF, forged fields, many-to-many guardians,
  admission numbering/duplicates, active-roll correction and constraints, lifecycle
  closure/archival, all enrollment transitions and stale forms, history protection,
  bounded CSV validation/ownership/expiry/revalidation/rollback/replay, image validation,
  private object-scoped delivery and failed-write cleanup, invalid identifiers,
  concurrent admissions/transfers and a legacy-schema upgrade rehearsal.
- Django system check and production deployment check: zero issues reported.
- Migration drift: no changes detected. Pending migration check passed.
- Ruff check/format, installed dependency consistency and repository scan passed;
  repository scan reported no findings. Git whitespace checks passed.
- Installed headless Chrome: four-role authentication/dashboard/chart/navigation
  regression passed, plus academic setup, admission form, import preview entry,
  guardian directory and teacher directory at desktop and mobile sizes. Screenshots
  are local, ignored artifacts under `.local/previews/`. No browser application writes
  were used beyond authentication/audit events; workflow writes use the isolated test DB.
- Temporary preview server stopped after verification. No deployment performed.

Local execution logs are ignored under `.local/`; the final test run is recorded in
`school-operations-verification.log`. Production storage durability, real SMTP,
MFA, backup/restore and operational scheduling remain outside local verification.
