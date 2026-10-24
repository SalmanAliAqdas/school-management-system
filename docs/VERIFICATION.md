# Foundation verification

## Phase 8 verification procedure

Run the complete PostgreSQL suite and `scripts/phase8_browser.py` against its owned disposable
database. Also run system/deploy checks, migration drift/pending checks, Ruff, static collection,
repository scanning, preservation checks, and domain integrity queries. Never point destructive
browser QA at the preserved development database.

Release verification on 24 October 2026 passed: 474 PostgreSQL tests in 724.538 seconds;
13 focused Phase 8 tests; Django system and production checks; migration drift and pending
migration checks; Ruff lint/format; dependency consistency; static collection; repository secret
scan; and installed-Chrome desktop/mobile journeys. The browser script exercised employee HR and
released payslip access, librarian circulation, student library/certificate access, guardian child
transport scope, inventory stock/assets, protected PDFs, minimal public verification, and denied
unrelated salary access using a uniquely named disposable database. Preservation verification
matched 2,810 baseline rows across all 124 original tables after the additive migration.

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


## Phase 3 attendance verification - 23 October 2026

This section records the completed Phase 3 verification scope.

- Baseline before changes: Phase 2 migrations current and all 130 PostgreSQL tests passed.
- Final suite: **185 tests passed**, zero failures/errors. It includes every earlier
  authentication/dashboard/admissions regression, dated roster and policy tests,
  database final-record guards, correction/leave approvals, guardian notice history,
  safe scoped CSV/PDF output, concurrent finalization/decisions and query scaling.
- Six new migrations applied successfully to the existing local PostgreSQL database.
  Migration drift/pending checks and Django system/production checks passed.
- Ruff lint/format, pip dependency consistency and repository/identity scans passed.
  No secrets or local account identities were found in commit candidates.
- An isolated, randomly named PostgreSQL browser database was created and removed
  by scripts/attendance_browser.py. Installed headless Chrome verified four roles,
  eight desktop/mobile screens, bulk present, draft/final submission, correction
  review, leave submission/approval, scoped guardian/student access and CSV/PDF.
- A mobile table-label overflow found during browser QA was fixed and rechecked.
  The runtime application CSP remains unchanged. Private screenshots are ignored
  under .local/previews/attendance/; test logs are ignored under .local/.
- Fictional demo extension created 53 student registers/106 entries, 19 staff
  registers/42 entries, two calendar exceptions, three correction examples, three
  leave requests and fourteen absence notice history rows in the local demo.
- Pre/post checks confirmed every existing account password/privilege fingerprint
  and the existing student/enrollment counts were unchanged. No database reset or
  administrator password change occurred. No production deployment was performed.

User acceptance with real operational policy, assistive technology, physical printers,
large school datasets and multilingual PDFs remains necessary before real-school use.
The repository's Actions tab supplies the pushed-commit CI evidence.


## Phase 4 examination verification ? 23 October 2026

This is the current verification scope. The baseline was a clean `c716d27` checkout,
matching GitHub main, with all 185 existing PostgreSQL tests passing.

- Final complete suite: **251 PostgreSQL tests passed**, zero failures/errors, including
  all prior authentication, dashboards, admissions/enrollment and attendance regressions.
  The final run completed in 149.923 seconds on the local verification machine.
- Sixty-six new examination tests cover setup/roster eligibility, grade gaps/overlaps
  and boundaries, Decimal weights/rounding, absence/exemption/missing/withheld states,
  teacher subject restrictions, controller/principal scope, independent reviews,
  state transitions, source consolidation/retakes, private rankings, recommendations,
  notifications, direct URLs, CSRF, CSV/PDF authorization, historical image/policy
  protection and query bounds. Three concurrent-write tests verify one winning marks
  submission, publication and correction decision without duplicate versions.
- Five additive examination migrations applied to the existing local database. The
  legacy migration-upgrade rehearsal passes as part of the complete suite. Migration
  drift/pending checks report no changes or unapplied migrations.
- Django system check and production deployment check report zero issues. Ruff lint
  and formatting pass; `pip check` reports no broken requirements. Production-settings
  static collection passes. No production deployment was performed.
- Repository scan including local identity checks reports no findings. Logs, private
  fingerprints, databases, uploads, generated PDFs and screenshots remain ignored.
- Installed Chrome ran `scripts/examination_browser.py` in its own randomly named test
  database. Actual UI writes verified administrator session/cohort/subject/component
  setup and scheduling, teacher draft/submission, independent controller review,
  principal approval, publication, correction/republication, student/guardian portal
  isolation, PDF download, CSV and desktop/mobile layouts. JavaScript error checks and
  horizontal-page-overflow assertions pass. Screenshots remain ignored under
  `.local/previews/examinations/`; the script stops its owned server and removes only
  its owned test database.
- Browser inspection identified and fixed school-local report issue-date formatting.
  A PDF reproduction test identified variable document metadata; deterministic output
  now passes a byte comparison after the source logo is replaced/deleted.
- Publication now shares grading context and batches guardian-recipient lookup rather
  than issuing queries per candidate. Bounded-query coverage passes for teacher scope
  and multi-candidate publication.
- Repeatable fictional data includes six examination/report sessions, 36 candidates,
  30 marks sheets/60 entries, 24 snapshot report cards and approved/rejected/pending
  correction examples, while preserving all pre-existing records.
- Final preservation comparison found **no differences in 431 original rows across
  26 tables**, including every existing user password and privilege field, student,
  guardian, enrollment, teacher assignment, attendance and audit record. No database
  reset, existing administrator password change or unexpected privilege-flag change
  occurred. Managed roles gained only the explicitly documented examination grants.

Private execution evidence is retained in `.local/phase4-final-tests.log`,
`.local/phase4-browser-final.log` and preservation fingerprints. Production-scale load,
real-school policy acceptance, assistive-technology review, physical printing and
multilingual PDF typography remain manual/operational validation. The completion
report supplies the pushed commit and GitHub Actions workflow link; no later phase
was implemented.


## Phase 5 finance verification (23 October 2026)

- Baseline `2d8f38ff19c5dee4508a957d77c8eb786a6a93ec`: 251 tests passed.
- Complete local PostgreSQL regression suite: **329 tests passed, zero failures/errors**,
  including 78 finance tests and all original authentication, admissions/import,
  attendance and examination tests. The complete run took 423.428 seconds locally.
- Independent PostgreSQL connections verify duplicate collection and invoice generation,
  competing refund reservations, and refund/allocation races. No overspending or
  duplicate permanent posting is accepted. Deferred commit coverage rejects unfinished
  journal entries. Migration downgrade/upgrade rehearsal retains issued invoices,
  original receipt snapshots and restored history guards in a disposable test database.
- Financial checks reconcile journal balance and every affected student's receivable,
  advance, funded deposit and uncollected deposit against permanent source documents.
  The fictional local ledger has 22 balanced entries, six issued invoices, four
  collections, one refund and one approved/paid expense. Re-running the finance seed
  does not overwrite an initialized ledger.
- Seven additive migrations applied to the existing PostgreSQL database. All 1,363
  pre-existing rows across 50 app tables have matching original SHA-256 fingerprints.
  No old password, administrator flag, academic/attendance/examination/publication or
  audit row changed. New fictional rows and finance role grants are explicitly additive.
- System check, production deploy check, migration drift/pending checks, Ruff lint and
  format, `pip check`, production static collection and repository/private identity
  scan passed. The scan reported zero findings. Runtime logs and snapshots remain ignored.
- `scripts/finance_browser.py` owns its uniquely named disposable PostgreSQL database,
  in-memory fictional passwords and local WSGI/Chrome process. It shuts down its server
  and removes only its owned test database. Desktop/mobile screenshots stay ignored at
  `.local/previews/finance/`. It exercises administrator fee setup, billing preview/
  generation/approval/issue, expense request/approval/payment, concession/refund review,
  cashier partial payment, receipt PDF/print, staff report PDF, student/guardian scope,
  unauthorized collection/export attempts, JavaScript errors and horizontal overflow.
- Visual review corrected currency-place formatting and replaced raw implementation
  representations in opening balances with ordinary financial labels. Browser checks
  use the formatted amount shown to users rather than raw stored numeric strings.

Private evidence: `.local/phase5-baseline.log`, `.local/phase5-final-tests.log`,
`.local/phase5-finance-final.log`, `.local/phase5-browser-final.log`, security scan and
preservation results. The completion report provides the final commit/Actions link.
No production environment was deployed and Phase 6 was not started.


## Phase 6 portal verification (23 October 2026)

- Clean starting checkout: `8eaf1f719c21fb05695d0f041d164679faf3bd04`.
  Actual baseline: **329 PostgreSQL tests passed**, zero failures/errors, in 295.327 seconds.
- New authorization and composition coverage includes multiple children, child selection,
  immediate revocation, role preference invalidation, mixed administrative/personal scope,
  publication/withholding and report versions, finance policy/ledger consistency, source
  inbox read-state/pagination, current/historical assignments, employment dates, password
  change, CSRF, no-data handling and query growth across children/classes.
- `scripts/portal_browser.py` ran installed headless Chrome using a uniquely named
  disposable PostgreSQL database, in-memory credentials and a loopback-only WSGI server.
  It exercised student dashboard/attendance/results/report/PDF/fees; guardian results and
  fees for two children, real child switching, inbox read state and immediate revocation;
  teacher assigned class, attendance draft, marks draft, personal attendance and leave;
  unauthorized student/report/journal URLs; and 390px/320px layouts without horizontal
  page overflow. Enter/Escape navigation restored keyboard focus. No JavaScript errors
  were recorded. Screenshots were visually inspected and remain ignored under
  `.local/previews/portals/`. The helper removes only its owned test database.
- System/production checks, migration drift/pending checks, Ruff lint/format, `pip check`,
  production static collection and repository/private-identity scan completed successfully.
  No migrations are introduced and all existing financial database guards remain enabled.
- `scripts/preservation_check.py` recorded and compared all **2,651 rows across 99
  original tables**, including auth, academic, attendance, examination, finance, audit
  and migration records. All table/row fingerprints match. It stores hashes and counts
  only in ignored local evidence; private row contents are not exported.
- Complete final PostgreSQL regression suite: **383 tests passed, zero failures/errors**,
  in 370.166 seconds, including 54 portal tests and all 329 previous tests.
  A focused final portal rerun verifies the final dashboard presentation changes. An earlier full run
  caught a source event-label mismatch and fictional history initialization after year
  archive; both were corrected using existing APIs and lifecycle guards.
- Phase 7, production deployment, online payments and external messaging were not run.
  Real-school policy acceptance, large-scale load and assistive-technology review remain
  outside this prototype verification.

Local evidence: `.local/phase6-final-tests.log`, `.local/phase6-browser-final.log` and
`.local/phase6-preservation.json`. GitHub Actions provides independent PostgreSQL CI
for the pushed commit.

## Phase 7 teaching and communication verification (24 October 2026)

- Complete PostgreSQL regression suite: **461 tests passed, zero failures/errors** in
  439.232 seconds. The 78 focused Phase 7 scheduling, learning, communication,
  authorization, history-guard and concurrency tests also pass independently.
- Django system and production deployment checks, migration generation/pending checks,
  Ruff lint/format, `pip check` and the repository secret/private-file scan passed. The
  scan reviewed 409 commit candidates and reported zero findings.
- `scripts/phase7_browser.py` passed timetable draft/conflict/publication, role-scoped
  schedules, homework file submission and grading, guardian feedback, event approval,
  authorized messaging/reply, unrelated-user denial, tablet/390px/320px overflow,
  keyboard navigation and JavaScript console checks.
- The retained `scripts/portal_browser.py` passed student, guardian and teacher journeys,
  including attendance and marks drafts, immediate access revocation and protected
  reports. Its register journey now uses the seeded draft's date so weekend/holiday
  execution remains deterministic.
- The pre-upgrade preservation check matched **2,654 rows across 99 original tables**.
  After all 12 additive migrations and role synchronization, the same row fingerprints
  match. Additions were limited to 12 migration rows, 25 content types, 105 permissions,
  14 group-permission links and new Phase 7 schema. Existing accounts, passwords,
  school records, attendance, reports, finance journals and audit rows were unchanged.
- A full-suite failure exposed a date-boundary issue in fictional submitted homework;
  the demo seed now permits late submission for intentionally pre-submitted examples
  while the production submission service retains strict configured deadline checks.

No production deployment or Phase 8 implementation was performed. Ignored screenshots
remain under `.local/previews/phase7/` and `.local/previews/portals/`.

## Phase 9 analytics and operational-preparation verification (24 October 2026)

- Clean starting baseline: **474 PostgreSQL tests passed** in 794.833 seconds at Phase 8 commit
  `5c112305f3d7866098a8bc475f580acfda2dc81a`.
- Final complete regression: **484 tests passed, zero failures/errors** in **1287.176 seconds**.
  Ten focused Phase 9 tests cover saved-record KPI boundaries, missing attendance, explicit
  dashboard permission, payroll confidentiality, relationship revocation, date validation,
  formula-safe/no-store export, separate export authority, health privacy, demo isolation and
  role-appropriate navigation.
- Representative executive aggregation over the preserved fictional database completed in
  **290.207 ms with 27 SQL queries** and returned six active students. This is a development
  measurement, not a production capacity guarantee; larger datasets still require load testing.
- Installed headless Chrome passed administrator dashboard/year filter, reporting center, CSV
  download, authorized payroll, student and guardian progress, unrelated-child and salary denial,
  guided demo, keyboard navigation, console monitoring, and desktop/tablet/390px/320px overflow
  checks in an independently named disposable PostgreSQL database. Generated screenshots remain
  ignored under `.local/previews/phase9/` and contain fictional test records only.
- A 939,748-byte PostgreSQL custom-format backup restored into a random disposable database in
  **7.835 seconds**. Verification found 85 migration records, 12 representative users and zero
  unbalanced journals; the restore database was then dropped. This is a measured rehearsal, not an
  RTO guarantee. Backups remain ignored beneath `.local/backups/`.
- Final Django system/deployment checks, migration drift/pending checks, operational database/
  ledger/stock check, Ruff lint/format, dependency consistency, production static collection and
  repository secret/private-data scan passed. The scan covered 505 commit candidates with no
  findings.
- Preservation verification matched all **3,084 baseline rows across 173 original tables**.
  Additions were limited to one migration, four permissions, three managed roles and 101 managed
  role-permission links. No original business, account, password, journal, payroll, academic,
  communication or audit row fingerprint changed.

Phase 9 did not deploy, create a hosted database, publish a public demo, upload private media or
begin Phase 10. Provider-scale load, production object storage, external monitoring, legal retention
approval, assistive-technology review and a final independent security/financial audit remain open.
