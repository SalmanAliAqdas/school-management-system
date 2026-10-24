# Implementation status

Phase 9 is implemented as an additive read-side analytics and operational-preparation layer.
Leadership receives saved-record executive KPIs with year/date filters; sensitive finance and
aggregate payroll values appear only with their existing domain permissions. The integrated
reporting center delegates to established module reports and adds bounded student, library,
inventory and certificate exports. Individual progress remains relationship/assignment scoped.

The development prototype now includes informational data-quality findings, an opt-in guided
fictional demo, minimal liveness/readiness endpoints, operator diagnostics, hardened production
startup validation, CI deployment checks, private PostgreSQL backup tooling and a measured
disposable restore workflow. No live deployment, hosted production database, public demo or Phase
10 audit has been performed. See `docs/ANALYTICS_DICTIONARY.md`, `docs/REPORTING_GUIDE.md`,
`docs/DEMO_GUIDE.md`, `docs/DEPLOYMENT_RUNBOOK.md` and `docs/PRODUCTION_READINESS.md`.

Phase 8 is implemented through six additive applications: HR, payroll, library, transport,
inventory/assets, and certificates/documents. They reuse existing identities, attendance/leave,
the Phase 5 ledger, portal authorization, protected PDF patterns, audit events, and notifications.
PostgreSQL and concurrency coverage is in `tests/test_phase8*.py`; release evidence is recorded in
`docs/VERIFICATION.md`.

Phase 7 timetable, homework, calendar, announcement and secure communication workflows
are implemented over the retained Django/PostgreSQL modules and Phase 6 portals. The
complete PostgreSQL regression suite passes: **461 tests, zero failures/errors**,
including 78 Phase 7 tests and all 383 existing Phase 1-6 tests.

## Phase 7 capabilities

- Conflict-checked, versioned weekly timetables with rooms, availability, workload,
  publication, dated bookings, substitutions, temporary roster access and reports.
- Published homework with deadlines, private immutable submission versions, protected
  attachments, review, grading, released feedback, guardian monitoring and analytics.
- Audience-scoped school events and announcements with independent approval, history,
  cancellation and a combined school/lesson/homework/examination calendar.
- Relationship-revalidated parent-teacher and internal conversations, private files,
  rate/duplicate limits, reporting, moderation, retention policy and unified notices.
- Student, guardian and teacher navigation and summaries integrated with current
  enrollments, guardian links and active teaching assignments.
- Desktop/tablet/390px/320px Chrome journeys, keyboard navigation and JavaScript checks
  passed in owned disposable PostgreSQL databases.
- Twelve additive migrations applied. All **2,654 rows across 99 original tables** match
  their saved fingerprints; only additive migration/content-type/permission metadata
  and new Phase 7 schema were introduced.

See [teaching and communication policy](docs/PHASE7_TEACHING.md),
[implementation plan](docs/PHASE7_PLAN.md), [navigation](docs/NAVIGATION.md) and
[verification](docs/VERIFICATION.md). No production deployment or Phase 8 work was done.

## Phase 6 capabilities

- Personalized student/family summaries, current child switching and read-only profiles.
- Policy-based attendance calendars, history, trends and authorized PDF links.
- Published result/report versions, progress charts and existing protected report PDFs.
- Separate fee balances, issued invoice allocations, receipts and account statements.
- Existing-data academic calendars and categorized, paginated source notification inbox.
- Assigned-class/subject teacher workspace, rosters, limited student views and guarded
  register/marks workflows; personal staff attendance and leave.
- Safe role/display preferences, contact-phone edits and Django password change.
- Service-level protection against permanent teacher writes from historical assignments.
- Desktop and 390px/320px Chrome journeys, keyboard navigation and JavaScript checks passed
  in an owned disposable PostgreSQL database.
- Original database preservation: all 2,651 rows across 99 tables match their fingerprints.
  Existing accounts, passwords, privileges, snapshots, ledgers and audit records are intact.

See [portal policy and UX](docs/PHASE6_PORTALS.md), [navigation](docs/NAVIGATION.md),
[implementation plan](docs/PHASE6_PLAN.md) and [verification](docs/VERIFICATION.md).
Phase 7 builds on these retained Phase 6 capabilities.

## Phase 5 implementation record

Phase 5 fees, billing, manual payments and financial management are implemented on
the existing Django/PostgreSQL architecture. Phases 1-4, the original administrator
account and historical school records are retained. No production deployment was performed in Phase 5.

## Completed Phase 5 capabilities

- Configurable school currency/precision, controlled numbering, financial years and
  periods, manual payment methods, masked account identifiers and financial policies.
- Dated class/section/student fee structures, historical revisions, individual
  overrides, recurring/one-time categories and explicit enrollment billing rules.
- Approved fixed/percentage scholarships/concessions, sibling eligibility, controlled
  stacking/order, ceilings, expiry, one-time consumption and dated fine exemptions.
- Individual/class batch billing with a bound preview/confirmation, idempotent cycle
  generation, itemized snapshots, independent approval and explicit invoice issue.
- Partial/multiple invoice allocations, advances, manual cash/bank collection,
  duplicate/reference protection and immutable branded printable/PDF receipts.
- Permanent balanced double-entry postings, source document links, reproducing student
  statements and separate receivable, advance, funded deposit and uncollected deposit
  balances. Deferred fees require explicit recognition; cash is not all revenue.
- Optional non-compounding fixed/percentage late fees with grace, caps, idempotency,
  holidays, independently approved exemptions and compensating fine waivers.
- Independent correction/credit/write-off, refund and returned-payment reversal
  workflows, pending funding reservations, preserved original documents and audit links.
- Expense requests, private sanitized receipt scans, independent approval, payable
  accrual and one manual disbursement; controlled opening entries and account transfers.
- Manual reconciliation with reserved transactions and independent approval; financial
  closing/reopening evidence and blocked posting into closed dates.
- Finance overview, charts, outstanding/aging, date/year/class reports, trial balance,
  collection summaries, invoice/receipt/expense/collection/trial CSV/PDF registers.
- Relationship-scoped student/guardian invoice, receipt and statement access, child
  selection, current-link revocation, PDF downloads and deduplicated internal notices.
- Eleven retained managed roles plus an optional custom cashier permission set.
  Cashiers can enter collections without configuration, approval, export or journal powers.
- Gated repeatable fictional examples and a scheduler-friendly draft billing command.

## Working interfaces

| URL | Purpose |
| --- | --- |
| `/finance/` | Finance overview, controls, configuration and charts |
| `/finance/setup/<kind>/` | Settings, accounts, years, periods, methods, categories, structures, lines, assignments, concessions, cycles, expense categories |
| `/finance/billing/` | Student/class preview and confirmed draft generation |
| `/finance/invoices/` | Searchable invoice register and preserved invoice details |
| `/finance/collect/` | Manual cashier collection and invoice allocations |
| `/finance/receipts/` | Receipt register, current reversal overlay, print and PDF |
| `/finance/students/` | Staff or linked-family accounts and dated statements |
| `/finance/allocate/` | Allocation of existing student advance credit |
| `/finance/requests/` | Independent decisions, corrections, refunds and reversals |
| `/finance/expenses/` | Expense requests, private evidence and approved payment |
| `/finance/reconciliation/` | Statement matching and review preparation |
| `/finance/reports/` | Outstanding, aging, collections, expenses, trial balance and exports |
| `/finance/journal/` | Immutable journal and source documents |
| `/finance/notices/` | Current relationship-scoped internal finance notices |

## Database and preservation

The new `finance` app contains 36 models and seven additive migrations:

1. `0001_initial`: complete finance schema, checks, uniqueness and date exclusions.
2. `0002_assignment_scope`: optional individually assigned structure scope.
3. `0003_financial_guards`: immutable documents/journals, complete balanced commit,
   allocation ownership/capacity, approval, financial dates and currency guards.
4. `0004_financial_sources`: used-definition, compensating entry and history protection.
5. `0005_optional_currency_symbol`: optional display symbol.
6. `0006_late_fee_exemptions`: independently approved dated student exemptions.
7. `0007_policy_history`: policy ranges and reconciliation/exemption history guards.

All seven applied to the existing PostgreSQL database. No prior migration was deleted
and no original database was reset. Preservation fingerprints confirm all **1,363
original rows across 50 tables unchanged**, including user passwords/privilege fields,
school configuration, students/guardians, enrollments, attendance, examinations,
publication snapshots and audit records. Managed groups gained documented finance
permissions. New fictional finance documents reconcile through 22 balanced entries:
six invoices, four payments, one refund and one approved/paid expense.

## Verification

- Starting baseline: **251 PostgreSQL tests passed** on `2d8f38f`.
- Complete local regression suite: **329 tests passed, zero failures/errors**.
  This includes 78 finance tests covering calculations, dated transitions, discounts,
  allocations, concurrency, reservations, refunds, reversals, source immutability,
  permissions/object isolation, exports, files, closing and migration rehearsal.
- Django system/production checks, migration drift/pending checks, Ruff lint/format,
  dependency consistency and production static collection passed.
- Repository and private identity scan: no findings. Private uploads, generated files,
  database credentials, fingerprints and screenshots remain ignored.
- Installed Chrome verifies real administration/cashier/approval/portal workflows in
  an independently named disposable PostgreSQL database. Browser evidence and final
  GitHub commit/Actions result are recorded in the completion report.
- See [finance policy](docs/FINANCE_POLICY.md), [plan](docs/PHASE5_PLAN.md) and
  [verification](docs/VERIFICATION.md).

## Prior modules and operational limits

Authentication/dashboards, admissions/CSV imports, school academic administration,
student/staff attendance and examinations/results remain implemented and regression
covered. Phase 4's previously verified 251-test state remains the starting reference.

Phase 5 is a development prototype, not a certified production accounting system.
Independent financial, security, privacy and operational validation remains necessary.
Coarse serialization limits write throughput; reports require bounded selections.
Collection entry shows two invoice allocation slots; further allocations use existing
credit. Scheduling requires an operator-managed command invocation. Refunded original
payments cannot use the reversal workflow. Advanced replacement chains, multilingual
PDF typography, physical printing, production load, retention, backup/restore and
real-school acceptance require further validation. Detailed policies and other
constraints are explicit in FINANCE_POLICY.md. No real banking, payment gateway,
paid messaging, tax certification, payroll or production deployment was included
in Phase 5. Phase 6 builds on this retained foundation as described above.
