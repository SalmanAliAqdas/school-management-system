# Implementation status

School operations phase implemented on 22 October 2026, retaining the existing
Django/PostgreSQL architecture, authentication and scoped dashboards.

## Delivered in this phase

- School name/logo, address, contact details, principal information and settings.
- Academic year and term setup, activation, permanent closure and archival.
- Class, section and subject setup, year-specific class subjects and teacher assignments.
- Student admissions with automatic, serialized school-wide admission numbers.
- Student identity, admission/birth dates, status, image and dated placement history.
- Roll numbers with active section/year uniqueness and audited active-roll corrections.
- Transactional section transfers, promotion, withdrawal, graduation and transfer out.
- Guardian contact management and audited many-to-many child relationships.
- Teacher/staff directories, profile forms, employment details and teacher images.
- CSV template, bounded parsing, preview, validation, duplicate detection, owner-bound
  confirmation, expiry, single-use protection, atomic import and staged-data cleanup.
- Search, sorting, filtering and pagination; printable profiles, admissions and class lists.
- Explicit role and action permissions, scoped object reads/prints/images and CSRF checks.
- PostgreSQL constraints for case-insensitive admissions/source references, active
  enrollment/roll uniqueness, birth dates and overlapping placement date ranges.
- Database trigger protection for completed placements and placement identity;
  protected academic definitions and read-only historical Django admin records.
- Safe decoded PNG/JPEG uploads, metadata stripping, random private filenames,
  authenticated delivery, replacement cleanup and failed-admission image cleanup.
- Upgrade backfill preserving legacy admission numbers, enrollment rows and assignments.
- Operating guide, architecture/permission/security updates and expanded regression tests.

## Module status

| Module | Status | Boundary |
| --- | --- | --- |
| Core and branding | Implemented | School identity, contacts, principal, logo and printable branding |
| Authentication and dashboards | Retained | Existing login/reset/roles, scoped dashboard charts and directory access |
| Academic administration | Implemented | Years/terms, lifecycle, structure and assignments; historical protection |
| Admissions and enrollment | Implemented | Direct admissions, CSV and individual enrollment workflows |
| Guardians | Implemented | Contact profiles, multi-child/multi-guardian linking and access revocation |
| Teachers and staff | Implemented | Administrative profiles and assignments; HR/payroll remains separate |
| Attendance, examinations, finance, homework and timetable | Pending | Existing planned pages only |
| Notifications, HR/payroll, library, transport, inventory, certificates | Pending | Later implementation phases |
| Reporting | Partial | Scoped printable student/admission/class records and existing dashboard charts |
| Production operations | Pending | Durable storage, real SMTP, MFA, backups/restore and deployment validation |

## Verification

**130 PostgreSQL tests passed**, including the original 77 tests. Django system
and production checks, migration drift, dependency consistency, Ruff, repository
scan and Chrome desktop/mobile checks passed. Six new first-party migrations
were applied. Coverage includes role/object denials, imports, enrollment transitions,
concurrent admissions/transfers and a legacy migration upgrade rehearsal. Browser
checks cover four roles and five administration screens at desktop/mobile sizes
using fictional data. Detailed evidence is recorded in docs/VERIFICATION.md.

## Explicit boundaries

This phase implements the requested administration/admissions/academic workflows.
It does not implement application-document review, readmission, exceptional historical
record correction, scheduled transitions, bulk promotion, attendance/exams/payments
or payroll. These are separate workflows rather than hidden edit/delete shortcuts.
Uploaded images currently use private local storage; production durability and
operational orphan-file reconciliation require deployment configuration. Expired
CSV preview cleanup is provided as a command and requires an external schedule.

No deployment was performed. Local verification does not establish commercial
readiness; see docs/SECURITY.md and docs/SCHOOL_OPERATIONS.md.
