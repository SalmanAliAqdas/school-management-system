# Phase 5 finance implementation plan

Baseline: clean `2d8f38f`, 251 PostgreSQL tests passed. Private fingerprints cover
1,363 existing rows in 50 tables, including users and examination publication history.

## Accounting and historical boundaries

- Use a new finance app and the existing school, users, students, guardians,
  dated enrollments and academic years. Financial periods remain separate from
  academic periods. A single base currency is frozen once finance documents exist.
- Keep journal entries and their lines immutable after posting. Every monetary
  event has a unique source key and balanced Decimal debit/credit postings.
  Database guards and deferred balance checks complement transaction services.
- Separate student receivables, held advance credits, funded refundable deposits,
  uncollected deposit charges and deferred revenue. Cash collected is not all revenue.
- Invoice revenue recognition is configured per category: earned on issue only
  when the school declares the fee earned, otherwise deferred until explicit
  approved recognition. Deposits remain liabilities. No certified reporting claim.
- Freeze issued invoice/receipt identities, calculations, branding and images.
  Later class changes or fee revisions affect prospective billing only. Explicit
  credits, reversals and replacement documents preserve the originals.
- Configure billing eligibility as period-start, any overlap or calendar-day
  proration. Proration follows each historical placement and effective fee revision;
  transfers do not charge two full overlapping class rates. Withdrawals end future
  eligibility without changing issued documents or academic access.

## Implementation sequence

1. Add financial configuration, chart/control accounts, years/periods, fee categories,
   revisioned structures, assignments, concessions and billing cycles.
2. Build Decimal billing services, deterministic discount order/caps and idempotent
   per-student/cycle generation, then independently approved invoice issuance.
3. Add manual payment intents, unique references/idempotency, immutable receipts,
   credit lots, line-level allocations and compensating allocation releases.
4. Build independently reviewed refunds, payment reversals, credits/write-offs,
   fine waivers, account openings/transfers and deferred revenue recognition.
5. Add expense requests/private scanned receipts, payable approval/payment,
   manual cash/bank reconciliation and controlled period closing/reopening.
6. Expose scoped financial/student views, branded PDFs, CSV/print reports, accurate
   dashboards/aging/trial balance, reminder rules and internal notifications.
7. Extend the gated fictional PKR seed without changing prior records. Test money
   invariants, role/object boundaries, concurrency and all earlier modules; run
   installed-Chrome workflows in an owned disposable test database.
8. Verify preservation, migrations/checks/security, update documentation, commit and
   safely push main, then verify Actions. No deployment, payroll or Phase 6 work.

## Lock and approval policy

The singleton finance configuration lock serializes money mutations for this
prototype, followed by year/period/document/credit locks in a consistent order.
It also serializes period closure with posting and concurrent award/issue actions.
All public service methods enforce capabilities. Material corrections and refunds
always require a different approver; thresholds add senior-approval requirements.
Pending refund/reversal/reconciliation requests reserve the affected funds/lines.

Cashier capabilities are a separable permission bundle, without journal/report or
approval rights. Existing managed roles receive only documented finance grants.
Student/guardian reads use current role and guardian links; teachers have no default
financial access. Bank identifiers and expense attachments remain staff-only.
