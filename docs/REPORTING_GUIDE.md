# Integrated reporting guide

Authorized users open `/analytics/reports/`. Categories are hidden unless the account has the
underlying domain permission. Native attendance, examination and finance reports remain the source
for their detailed calculations; Phase 9 links to them rather than recreating them.

Phase 9 tabular reports accept an academic year and inclusive date range. HTML previews show at
most 100 rows. CSV/PDF requires `core.export_analytics`, refuses unbounded 5,000-row results, uses
fixed safe filenames and private no-store responses, and records an audit event. CSV values starting
with spreadsheet formula characters are prefixed safely. Export authorization is identical to the
HTML source; direct URL changes do not broaden scope.

Student progress at `/analytics/students/<id>/` is descriptive. Administrators need global student
scope, students see self, guardians need a current explicit link, and teachers need a real teaching
assignment. It includes finalized attendance, immutable published results, homework state, placement
history and released feedback—never draft marks, private feedback or predictive risk labels.
