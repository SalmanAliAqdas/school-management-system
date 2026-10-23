# Security foundation and operational limits

The application is a fictional-data prototype. Foundation controls are not a
certification of commercial readiness.

The Phase 1 commit boundaries, dependency/secret scans and clean-install results
are recorded in [REPOSITORY_REVIEW.md](REPOSITORY_REVIEW.md). The reusable
`scripts/repository_check.py` check also runs in CI. Private local files and
credential stores remain excluded; public test credentials are fictional fixtures.

## Implemented boundaries

- Environment-only production secrets; production refuses short/missing keys.
- Django password hashing/validation, inactive-account checks, session key rotation,
  POST-only logout, CSRF middleware and POST forms.
- One-hour, single-use password reset tokens; generic unknown-email responses.
  Local reset messages go to the development console. Production uses SMTP.
- Database-backed django-axes throttling shared across workers: five failures for
  either a username or the socket IP trigger a 15-minute lockout. Forwarded client
  headers are ignored. Run `python manage.py axes_reset` for an authorized local
  unlock and periodically `python manage.py axes_reset_logs --age 30` to prune access logs.
- Capability checks plus object-scoped selectors. Restricted history is filtered
  independently from profile visibility. Administrative bypass is explicitly limited.
- HttpOnly session and CSRF cookies, SameSite Lax, private/no-store authenticated
  responses, a local-asset content security policy, frame denial, and no-sniff.
- HTTPS redirects, secure cookies and HSTS in production. Proxy HTTPS trust is
  opt-in and requires a proxy that strips client-supplied forwarding headers.
- Safe generic error pages and a health response that does not expose DB details.
- Authentication, student-detail access and settings-write audit events omit
  credentials, request bodies, reset tokens and personal metadata.
- Authorized PNG/JPEG profile/logo uploads are bounded, decoded, metadata-stripped,
  resized and re-encoded to randomly named private PNGs. Image routes authenticate
  and enforce record scope. No public media route exists. PDF document workflows
  remain unimplemented beyond the original reusable validator.
- Demo initialization requires DEBUG **and** ALLOW_DEMO_DATA and a locally supplied
  password. Existing account passwords are preserved on repeat runs.

## Required before real school data

Establish retention/consent policy, tested backups and restores, secrets rotation,
dependency updates, MFA for administrators, monitoring and incident procedures.
Use a least-privileged production database account and restrict admin access.

At a reverse proxy, username throttling remains effective, but socket-IP throttling
may group all users behind one proxy. Configure trusted client-IP extraction only
after verifying that ingress strips spoofable headers; test the exact deployed
topology before enabling real accounts. Configure SMTP and exercise delivery and
bounce handling. Reset request abuse controls and uniform response timing need a
deployment-level review. Email account existence may be inferred from timing.

Audit rows are read-only through application UI but not cryptographically immutable;
database operators can change them. Retention, offsite/tamper-evident storage, all
future writes, exports and bulk reads require a reviewed audit policy. Django admin
changes also have Django's own LogEntry history, not a unified audit feed.

Do not expose media through WhiteNoise or a static web root. Future file workflows
need malware scanning, private storage, ownership checks, authenticated downloads,
attachment headers and file-type validation beyond the initial PDF signature gate.
Render's ephemeral filesystem cannot serve as durable document storage.

Enrollment writes use ordered year/student locks, a database overlap exclusion
constraint, global active-placement uniqueness and a database history guard.
CSV confirmation locks its batch, revalidates all rows and imports atomically.
Admissions serialize number allocation and duplicate checks. Tests exercise
simultaneous admissions and transfers. The app is single-school; multi-school tenancy needs a separate access
and migration design. No attendance, mark entry, payments or payroll actions exist.

Application audit events cover academic/profile/link/admission/transition/import
writes without storing row contents. Expired CSV personal rows need scheduled
`purge_admission_previews`; successful confirmation clears rows immediately.
Private file storage still needs durability, backups and orphan reconciliation in
production. Do not grant application users permission to alter schema or triggers.

## Attendance security boundary

Phase 3 uses existing student/guardian/teacher selectors and explicit attendance
capabilities. Registers validate complete dated rosters on the server. Corrections
retain original/revised data with separate requester/reviewer and a configurable
window. Database guards prevent finalized-row mutation without its matching approved
correction; enrollment and employment edits cannot invalidate saved attendance.
Leave approval applies any recorded changes as explicit correction history.

Internal notices target currently authorized linked guardians, are idempotent by
revision, and retain supersession/read history. Revoked links immediately stop reads.
HTML, CSV and PDF reports share scope, validate filters and cap exports at 5,000 rows;
CSV formula prefixes are neutralized, PDF text is escaped and no remote content is
fetched. Attendance audit events contain identifiers/action names rather than request
bodies, medical reasons or personal row contents. Sensitive reasons remain restricted
inside the school database and require a reviewed retention policy for real use.

The attendance browser harness uses a newly created, randomly named test database,
in-memory credentials and loopback hosting. It removes only its own temporary test
database. No SMS, WhatsApp, email delivery, payroll or production deployment occurs.


## Examination publication and confidentiality

Phase 4 adds explicit examination capabilities and session/controller or exact
teacher assignment scope. Every write rechecks object authorization in a transaction.
POST/CSRF, exact rosters, Decimal validation and optimistic versions protect marks
entry and transitions. Principals approve where configured; independent review and
mandatory reasons protect corrections and visibility/remarks amendments. PostgreSQL
guards prevent direct ordinary updates to submitted marks, used policies, completed
decisions or issued snapshots. Database-owner access remains a trusted operator
boundary, as with the existing attendance safeguards.

Only authorized current publications appear in personal portals/analytics/exports.
Withheld snapshots contain no marks, grades, assessment/general remarks or positions;
current withholding also blocks old personal HTML/PDF/image URLs. Guardian links and
teacher/controller permissions are rechecked at read time. Notifications do not copy
restricted marks or private reasons. No public report verification URL is introduced.

Issued branding and sanitized private-image bytes are retained in immutable snapshots,
so no remote image is fetched while generating a PDF. Images use authorized snapshot
routes; responses are private/no-store. PDF strings are XML-escaped; CSV formulas are
escaped. Output is bounded and no official signature/seal is fabricated. Admin models
are read-only and the existing superuser-only admin gate is retained.

The development-only fictional seed remains explicitly gated and never changes an
existing account password or overwrites published sessions. Browser QA uses its own
randomly named test database and removes only that owned test database. Production
hosting, retention/access governance, backup/restore, real-school privacy review,
large-scale load, accessibility and multilingual PDF validation remain operational
work; no production deployment is included.

## Phase 5 financial boundaries

Finance keeps all money mutations atomic and serialized, with exact Decimal amounts,
unique idempotency/reference keys, source ownership validation, independent approval,
material/backdate senior review, pending refund reservations and permanent audit links.
PostgreSQL protects posted journal lines/headers, issued documents, approval history,
used definitions, allocation/refund evidence and closing controls. A deferred trigger
rejects incomplete/unbalanced journal entries at commit. Student receivable/advance/
deposit balances are reproducible and independently reconciled to source documents.
No browser-supplied balance is trusted. Reversed receipts remain preserved and marked.

Family views recheck current links/policy for every object and notification. Export
permissions and spreadsheet-safe CSV cells prevent unauthorized/formula-based exposure.
All mutation forms retain CSRF protection. Private sanitized PNG/JPEG expense scans
reuse bounded image handling and authenticated streaming. School bank identifiers are
masked in lists and visible only to configuration staff in edit forms. No card details,
CVV, PIN, bank passwords, real provider integrations or paid notifications are added.
Database-owner compromise, operational cash verification, financial policy acceptance,
retention and production-scale resilience remain outside prototype certification.
