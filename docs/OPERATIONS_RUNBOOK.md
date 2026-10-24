# Operations runbook

Use `/health/live/` for process liveness and `/health/` for database readiness; responses intentionally
contain no version, path, SQL, user or credential details. Operators run `manage.py operational_check`
for pending migrations, balanced journals and nonnegative stock. Keep diagnostic logs access
controlled and avoid passwords, tokens, documents, message bodies or unnecessary identity data.
Audit events remain the permanent record of sensitive application actions; logs are not a substitute.

Potential scheduled commands include fee draft generation, attendance/homework reminders, contract
and qualification expiry notices, library overdue notices, inventory warnings and backup monitoring.
They must be idempotent and invoked by the hosting scheduler with one-run concurrency controls. No
scheduler, Celery or Redis is installed, so none of these jobs should be represented as automatic.

For incidents: preserve logs/audit data, restrict access, identify the affected domain, validate
database/readiness, stop unsafe writes if necessary, create a backup, and use reviewed service-level
corrections rather than direct historical edits. Rotate compromised secrets outside the repository.
