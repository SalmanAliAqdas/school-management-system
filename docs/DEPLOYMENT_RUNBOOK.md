# Deployment runbook (preparation only)

SchoolOS requires Python, WSGI (Gunicorn), PostgreSQL and durable private file storage; static-only
hosting cannot run it. Provision a separate least-privilege production database with TLS where the
provider supports it, connection limits, monitoring and provider-managed backups. Never upload the
development database.

Required configuration includes a 50+ character `SECRET_KEY`, `DATABASE_URL`, `ALLOWED_HOSTS`,
HTTPS `CSRF_TRUSTED_ORIGINS`, timezone, SMTP details and explicit proxy trust. Production enforces
DEBUG/demo off, secure cookies, HTTPS redirect, security headers and HSTS. Confirm the chosen proxy
strips client-supplied forwarding headers before enabling `TRUST_PROXY_HTTPS`.

Build with `build.sh`; run `manage.py migrate`, `manage.py sync_roles`, `manage.py collectstatic`
and `manage.py operational_check`; start with the existing Gunicorn command. `/health/live/` is
liveness and `/health/` is database readiness. Create administrators interactively through a secure
operator channel, never a committed password.

Render configuration is a useful template for a web service plus managed PostgreSQL, but persistent
private media needs an independently assessed durable private store or disk with authenticated
application delivery and backups. Validate current provider features and costs before authorization.
Rollback means stop new traffic, restore the previous application artifact, and only reverse a
migration when its reviewed reverse operation preserves data. Database restore is a separate,
explicit incident procedure. Phase 9 performs no deployment.
