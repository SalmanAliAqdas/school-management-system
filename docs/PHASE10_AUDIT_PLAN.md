# Phase 10 final audit plan

## Baseline and safety boundary

- Starting commit: `0cf3512df975e2dee45a3d5572759278ef18975b` (`main`, clean and aligned with
  `origin/main` at inspection time on 2026-10-24 PKT).
- Documented Phase 9 baseline: 484 PostgreSQL tests and successful GitHub Actions run
  `40059422682`. Phase 10 re-runs all evidence and does not inherit a PASS merely from that record.
- Original PostgreSQL preservation baseline: 3,084 rows across 173 original tables, represented by
  ignored SHA-256 row-set fingerprints in `.local/phase9-preservation.json`; no private values are
  exported. Destructive tests use Django-created or explicitly named disposable databases.
- `.env`, media, database data, backups and credentials remain ignored. No production deployment,
  live-system penetration test, account deletion, credential change or historical migration rewrite
  is in scope.

## Workstreams and acceptance criteria

| Workstream | Evidence required for acceptance |
| --- | --- |
| Repository and architecture | All tracked source, migrations, settings, CI, dependency manifests and Phase 1-9 records inventoried; dirty work preserved. |
| Authentication | Login/logout, reset, throttling, inactive-user behavior, CSRF, redirects, session controls and audit events tested; no MFA claim. |
| Authorization and privacy | Direct routes, selectors, exports, PDFs and private files reject cross-role, cross-student and cross-family access. Revoked links and expired teacher scope are covered. |
| Finance | Decimal arithmetic, idempotency, balanced journals, approvals, reversals, closed periods, immutable history and control-account reconciliation are reproducibly tested. |
| Payroll | Effective dates, proration, deductions, independent approval, duplicate/concurrent finalization, immutable finalized history, payment and reversal journals are tested. External policy remains explicit. |
| Academic operations | Enrollment, examinations, attendance, timetables, homework and communications retain historical boundaries and reject stale/concurrent or unauthorized writes. |
| Phase 8 operations | Library, transport, inventory/assets and certificates have concurrency, eligibility, privacy, immutability and reconciliation evidence. |
| Analytics | KPI definitions match authoritative saved records, permission gates hold, dates/missing data are tested and representative query counts are bounded. |
| Database and migrations | Fresh PostgreSQL migration, no drift/pending migration, constraints and concurrency checks pass; upgrade evidence is non-destructive. |
| Configuration and supply chain | Deployment checks, secret scan, dependency consistency and current advisory evidence are recorded; unavailable live sources are disclosed. |
| UI and accessibility | Representative desktop, tablet, 390 px and 320 px journeys, keyboard use, labels, headings, errors, tables and overflow are inspected with actual browser evidence. |
| Backup and operations | Backup and restore are rehearsed into a disposable target; credentials do not enter command lines/logs; database and media recovery limits are explicit. |
| Release | Full checks are repeated after fixes, preservation is re-verified, findings and gates are candid, and only then is a reviewed non-force commit pushed and CI observed. |

Severity order is CRITICAL, HIGH, MEDIUM, LOW and INFORMATIONAL. Critical/high defects in scope
block release until fixed and regression-tested. Untested items are `NOT VERIFIED`, never inferred as
passing. Release evidence belongs in `VERIFICATION.md`; limitations belong in the risk and readiness
records.
