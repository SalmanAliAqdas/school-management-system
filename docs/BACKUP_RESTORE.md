# Backup and restore

Database and private media are separate backup sets. Run PostgreSQL tools from a trusted operator
host with restricted `.local/backups` permissions:

```powershell
.\.venv\Scripts\python.exe scripts\postgres_backup.py backup --bin-dir .local\postgresql\pgsql\bin
.\.venv\Scripts\python.exe scripts\postgres_backup.py rehearse --bin-dir .local\postgresql\pgsql\bin
```

The custom-format, timestamped dump is ignored by Git. The password is passed to PostgreSQL through
the child environment, not command arguments. Store encrypted copies in access-controlled durable
storage, define school-approved retention/rotation, monitor completion and periodically test restore.
Hashing and provider object-lock/versioning should be considered; neither proves application-level
consistency without a restore rehearsal.

Rehearsal creates a random `schoolos_restore_*` database, restores without changing ownership,
checks migration/user records and balanced finance journals, reports measured duration, and drops
only that validated disposable target. It refuses a backup outside `.local`. Never restore over the
configured database. Back up protected media with its authorization metadata and test it separately.
