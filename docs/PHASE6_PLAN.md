# Phase 6 implementation plan

The starting checkout is `8eaf1f719c21fb05695d0f041d164679faf3bd04` with no local
changes. Inspection found 329 existing tests, eleven managed roles, immutable
examination publications, scoped attendance/finance selectors and no assignment
date fields beyond academic-year scope and teacher employment dates. PostgreSQL
was stopped; its existing cluster is being resumed without initialization.

1. Establish the complete PostgreSQL regression baseline, check migrations and
   fingerprint existing tables before implementation. Keep all browser/test data
   in disposable databases. Do not reseed the original database.
2. Add a read-oriented `portals` package with student, guardian and teacher routes.
   Intersect existing selectors with the selected portal's explicit relationships;
   administrative or secondary roles must not enlarge a personal dashboard.
3. Build shared navigation, role switching, child switching, overview/profile,
   attendance, published results/report history, finance and calendar screens.
   Delegate domain writes and downloads to the existing guarded module workflows.
4. Add assigned-class/roster/limited-student teacher workspaces, current marks and
   register queues, personal attendance and leave links. Closed/historical years
   are read-only. Show only subject-authorized published academic data to teachers.
5. Aggregate source notifications using a database union for ordering/pagination;
   retain original read state and recheck authorization on reads and POST updates.
   Add safe phone/display preferences and Django password change without permitting
   unverified email or official identity changes.
6. Extend the explicitly gated fictional seed using existing identities, with
   repeat-run checks and no password/privilege changes.
7. Add portal privacy, publication, role, CSRF, no-data, boundary and query-budget
   tests; run the full PostgreSQL suite and representative installed-Chrome journeys
   in an isolated database at desktop, 390px and 320px widths.
8. Update standalone documentation; run system/production/migration/static/lint/
   dependency/secret checks; compare original database fingerprints. Review, commit,
   safely synchronize/push main without force and verify the pushed GitHub Actions run.

No new student, enrollment, attendance, examination or finance models are needed.
Phase 7 scheduling, homework, messaging and online payments remain outside scope.
