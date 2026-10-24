# Phase 8 implementation plan

Phase 8 adds six bounded school-operations applications over the verified Phase 7
commit `a6572c3006ce4bfaac258239c1b36348279f7566`. The starting PostgreSQL suite is
461 tests, all passing. Existing people identities, attendance/leave, finance,
portals, communications, audit and school-branding services remain authoritative.

## Safety and architecture

- Capture an ignored fingerprint baseline of every existing PostgreSQL table before
  applying additive migrations; verify all original rows again after the upgrade.
- Reuse `people.Staff` and `people.Teacher`; HR stores effective-dated employment
  detail and confidential records linked to those identities rather than copying them.
- Extend existing leave records with policy, entitlement and balance services; never
  create a second leave-request workflow or infer absence from a missing register.
- Post payroll only through Phase 5 journal services with Decimal values, balanced
  immutable entries, idempotent source keys and financial-period checks.
- Resolve student, guardian and staff access at read time. Private documents and PDFs
  have authenticated, object-scoped, no-store download endpoints.
- Finalized payroll, stock, circulation and issued-certificate records retain snapshots
  and correction/reversal history. Concurrent resource changes use row locks and
  database constraints.
- Browser and destructive verification use uniquely named disposable PostgreSQL
  databases. Phase 9/10, production deployment and external providers stay out of scope.

## Workstream checklist

- [x] A — HR: departments/designations, effective employment history, confidential
  documents/notes, qualifications/certifications, termination/rejoin, leave policy and
  balances, attendance summaries, performance reviews and training.
- [x] B — Payroll: components, salary revisions, periods, configurable proration,
  attendance/leave review, draft/approval/finalization/payment/reversal, balanced finance
  posting, protected released payslips and reports.
- [x] C — Library: title/copy catalog, borrower eligibility, issue/return/renewal,
  reservations, overdue/lost/damaged/waiver workflows, personal portals and reports.
- [x] D — Transport: vehicles, eligible staff assignments, routes/stops/trips, capacity
  and schedule conflicts, student assignment history, inspections/maintenance/incidents,
  scoped family views, notices and controlled finance links.
- [x] E — Inventory/assets: categories/items/locations, immutable receipts/issues/returns/
  transfers/adjustments, concurrent stock safety, low-stock reports, durable assets,
  custody/transfers/maintenance/disposal and expense links.
- [x] F — Certificates: configurable types/signatories, requests, eligibility, review,
  immutable issuance snapshots, branded PDF, revocation/replacement and minimal public
  verification using random non-guessable tokens.
- [x] Portal/navigation/notifications/demo integration completed for all six domains.
- [x] Targeted PostgreSQL suites, permission checks and migration drift pass after each
  workstream.
- [x] Full regression, production checks, static collection, lint/format, dependency and
  repository security scans pass.
- [x] Phase 8 Chrome journeys pass at desktop and mobile widths without console errors.
- [x] Original PostgreSQL fingerprints match after additive upgrade.
- [ ] Documentation completed; reviewed commit pushed to `main`; exact GitHub Actions
  workflow succeeds.

## Operating limits

This remains a development prototype. It provides no statutory tax conclusions, banking
or payment gateway, GPS tracking, government identity verification, fabricated signature,
paid messaging, automated depreciation or audited inventory valuation. Real employment,
tax, payroll, safety, retention, malware scanning and accounting policies require local
professional validation before production use.
