# Production readiness assessment

Phase 9 prepares configuration, documentation, health diagnostics, CI and restore tooling but does
not certify or deploy SchoolOS. Before real school use, independently validate employment/tax and
accounting rules, privacy/retention law, safeguarding, accessibility, threat modelling, penetration
testing, malware scanning, SMTP, private object storage, monitoring/alerting, capacity, disaster
recovery objectives, incident response, user support and provider contracts.

Protected photos, HR documents, homework attachments, financial evidence, payslips, certificates and
messages must never use a public media bucket. Production storage needs authenticated application
access, object-level checks, safe names/types/sizes, encryption, durable backups, retention/legal-hold
decisions and reviewed secure deletion. Ephemeral web-service disk is unsuitable.

Retention categories include student/enrollment/attendance/examination history, guardian details,
financial/payroll ledgers, communications, homework, employee files, certificates, audit events and
backup copies. Local experts must define periods and lawful deletion/archival rules; this repository
intentionally hardcodes none and makes no GDPR, Pakistani-law or other compliance claim.

Readiness remains **development prototype / pre-production assessment required**. Phase 10 is the
final professional audit and release-readiness review.
