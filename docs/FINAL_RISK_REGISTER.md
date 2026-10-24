# Final risk register

## Critical blockers

None confirmed by the repository and local verification performed for Phase 10. This does not mean
that an independent penetration test or production infrastructure assessment found none; neither has
occurred.

## High-priority blockers

- **Durable private storage and malware controls (software/deployment):** production media durability,
  private object policy, encryption/retention, backups and malware quarantine are not implemented and
  verified on a selected host.
- **Payroll/legal/accounting policy (external):** calculations and mappings have not been approved by
  qualified local payroll, tax, employment-law and accounting professionals.
- **End-to-end recovery (operational):** there is no deployed, scheduled, monitored, off-site database
  plus private-media backup and no approved/measured RPO or RTO.

## Medium risks

- No independent application/infrastructure penetration test.
- No production-volume concurrency, load or soak evidence.
- No complete screen-reader/user accessibility evaluation or WCAG conformance claim.
- No school-owner UAT, safeguarding/privacy impact assessment, retention approval or incident-response
  exercise.
- SMTP deliverability, bounce handling and password-reset operations remain unverified on a real provider.
- Monitoring, alerting, on-call ownership and centralized tamper-resistant audit-log retention are not
  established.

## Low risks

- Compatible dependency ranges are not a fully reproducible, hash-locked release artifact.
- Public certificate verification is capability-token based; Phase 10 disables response caching, but
  operators must also control proxy/access-log retention and abuse monitoring.

## Operational dependencies

Selected hosting must support Python/Django, PostgreSQL 17-compatible behavior, TLS termination,
durable private media, outbound SMTP, scheduled jobs, encrypted backups, log/metric export, alerting
and tested rollback. Render configuration is a starting template, not proof that a particular plan
meets these needs. Database migration and role synchronization remain explicit release operations.

## External validation required

Qualified reviewers must cover privacy/data protection, safeguarding, records retention, payroll and
employment law, tax, accounting policy, transport/safety operations and accessibility. School role
owners must approve the permission matrix and complete controlled UAT. These are not software defects
and cannot be closed by adding unit tests.

Detailed reproductions and remediation states are in `PHASE10_FINDINGS.md`.
