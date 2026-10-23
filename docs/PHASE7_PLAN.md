# Phase 7 implementation plan

Retain the Django/PostgreSQL applications and Phase 6 portals. Add scheduling,
learning and communications as explicit domain boundaries, reusing academic years,
teaching assignments, dated enrollment, guardian links, attendance policies and leave.

1. Inspect repository, record the actual regression baseline and fingerprint the
   current database independently of the older Phase 6 preservation evidence.
2. Implement transaction-serialized timetable drafts, validation, publication,
   dated substitutions, availability and operational reports.
3. Implement scoped learning assignments, immutable submission revisions, private
   attachments and explicitly released feedback with audit history.
4. Implement targeted events/announcements and relationship-checked conversations,
   moderation and integrated source notifications.
5. Extend the existing navigation, dashboards and calendars with accessible forms,
   weekly schedules, homework and communication workspaces.
6. Exercise PostgreSQL security/concurrency tests and isolated Chrome journeys;
   run all repository checks, verify preservation and document limits.
7. Review, commit and safely push main, then verify the exact commit's CI result.

No production deployment or Phase 8 modules. Browser/demo writes use an owned,
disposable database. Existing school records and credentials are preserved.

## Completion checkpoint

Implementation and local verification completed on 24 October 2026. The final suite
contains 461 passing PostgreSQL tests, including 78 Phase 7 tests. Both Phase 7 and
retained Phase 6 Chrome journeys pass. The additive schema is applied to the original
school database and all 2,654 baseline rows across 99 original tables retain their
fingerprints. The new form template remains separated from the retained academic
administration form to preserve existing workflows. Safe commit, push and exact-commit
GitHub Actions verification complete the remaining publication step.
