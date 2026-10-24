# Phase 9 implementation plan

Phase 9 starts from verified commit `5c112305f3d7866098a8bc475f580acfda2dc81a` and the
474-test Phase 8 PostgreSQL baseline. It adds analytics, reporting, demonstration and operational
readiness without deploying the application or beginning Phase 10.

## Dependencies and safety

- Existing domain selectors, published snapshots, attendance policy calculations and the Phase 5
  double-entry ledger remain authoritative. Analytics never writes or repairs source records.
- A fingerprint of every existing PostgreSQL table is captured before additive migration and
  compared afterward. Destructive, scale and browser exercises use uniquely named disposable
  databases.
- Executive access is a distinct permission. Detailed finance, payroll, HR and personal progress
  continue to require their existing permissions and object relationships.
- Exports are bounded, formula-safe, audited and generated from the same scoped querysets as HTML.
- Production preparation is configuration and documentation only: no hosted database, domain,
  billing, public demo, media upload or live deployment is authorized.

## Workstream checklist

- [x] A — Executive dashboard: year/date filters, accurate KPI cards, trends, drill-downs, recent
  data and responsive/print presentation.
- [x] B — KPI registry: executable metric definitions plus `ANALYTICS_DICTIONARY.md` covering
  sources, boundaries, exclusions, missing data, access and refresh behavior.
- [x] C — Academic analytics and scoped student progress: enrollment, attendance, published exams,
  homework, workload and transparent historical trends.
- [x] D — Finance/payroll analytics: invoices, collections, receivables/aging, concessions,
  refunds/deposits, expenses, ledger summaries and aggregate confidential payroll reconciliation.
- [x] E — Operational analytics: HR, library, transport, inventory/assets, certificates and pending
  approvals, using transaction histories as sources of truth.
- [x] F — Reporting center: categorized filtered reports, search/sort/pagination, bounded CSV/PDF,
  formula-injection protection and audit events.
- [x] G — Professional fictional demo: expanded roles/data, guided module experience, repeatable
  opt-in seed and disposable reset/setup instructions without committed credentials.
- [x] H — Production configuration: environment validation, secure logging, private-storage model,
  platform-neutral and Render-specific deployment guidance, rollback and admin provisioning.
- [x] I — Backup/restore/operations: safe commands, database and media separation, disposable
  PostgreSQL restore rehearsal, health/readiness diagnostics and scheduler guidance.
- [x] J — Tests, capacity measurements, accessibility/browser QA, documentation, preservation,
  reviewed commit, push and successful GitHub Actions run.

## Milestones

1. Record clean repository, migration and 474-test baseline; capture Phase 9 preservation evidence.
2. Implement permission model, KPI registry/selectors and executive/reporting routes with targeted
   correctness, boundary, query-count and export-security tests.
3. Complete academic, financial, payroll and operations reporting plus individual progress scope.
4. Extend fictional demo and add data-quality findings without automatic remediation.
5. Add production/health/backup tooling and perform a measured restore rehearsal in a newly named
   disposable PostgreSQL database.
6. Run full regression and Chrome journeys at desktop/tablet/390px/320px, finish documentation,
   re-verify all original data, then commit/push and observe CI.

## Principal risks and controls

- **Metric drift:** definitions are centralized and tested against saved source records.
- **Aggregation leakage:** general KPIs omit individual salary/private personnel data; scoped detail
  requires the underlying permission and relationship on every request/export.
- **Accounting misstatement:** cash, revenue, receivables, advances, deposits and approved expenses
  remain separate ledger concepts and are reconciled to posted journals.
- **Expensive queries/exports:** date bounds, ORM aggregation, indexes, pagination and hard export
  limits prevent whole-database materialization.
- **Unsafe operations:** backup credentials stay outside command lines where possible; restore
  rejects the configured application database and cleanup targets are explicitly validated.
- **Demo contamination:** demo mode is explicit, production rejects it, identities use reserved
  domains, and reset guidance applies only to disposable databases.

## Completion criteria

Every checklist item must have executed evidence: migration/system/deploy/Ruff/dependency/static/
repository checks, complete PostgreSQL regression, domain integrity checks, measured representative
queries, installed-Chrome verification, successful disposable restore, exact preservation match,
clean reviewed Git state and successful CI for the pushed Phase 9 commit. Remaining legal,
accessibility, capacity, storage-provider and operational limitations must be stated without a
production-readiness claim.
