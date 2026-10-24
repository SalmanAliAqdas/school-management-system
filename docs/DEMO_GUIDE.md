# Fictional demonstration guide

Demo initialization is explicit: use development settings, set `ALLOW_DEMO_DATA=True` and provide a
strong local `DEMO_PASSWORD`, then run `manage.py seed_demo`. The command is transactional,
idempotent, uses `example.invalid`, preserves existing passwords, and refuses colliding non-demo
identities. It never runs on application startup; production rejects demo mode.

The seeded roles cover administrator, principal, school administrator, academic coordinator,
teacher, student, multi-child guardian, accountant, examination controller, HR/payroll, librarian,
transport and inventory. Signed-in `demo.*` accounts may open `/demo/guide/` to follow admission,
attendance, published results/report cards, invoices/payments, portals, timetable/homework/feedback,
messages, payroll, circulation, transport, stock/assets, certificates and executive analytics.

Never reset the preserved database for a demo. For a clean presentation, create a separately named
disposable PostgreSQL database, migrate/sync roles, seed it, demonstrate, then remove that exact
database. Do not publish credentials, screenshots of non-fictional records, or unrestricted portals.
