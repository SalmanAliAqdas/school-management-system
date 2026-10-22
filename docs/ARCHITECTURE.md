# RumiWare SchoolOS architecture

## Scope and decisions

SchoolOS is a single-school modular Django monolith. Django templates, Bootstrap 5,
local CSS, and small JavaScript modules provide the interface. PostgreSQL is the
application and test database. Django 5.2 LTS and Python 3.12–3.14 are the supported
baseline. No separate API server, job broker, or frontend build tool is required.

Foundation authentication, access policy, scoped dashboards and audit events are
retained. Phase 2 adds academic administration, admissions, enrollment transitions,
guardian relationships, teacher/staff profiles, CSV imports and private images.
Phase 3 adds enrollment-aware attendance, staff attendance/leave, internal absence
notices, corrections and attendance reporting. Phase 4 implements examinations,
weighted grading, review/publication, report cards and result portals. Finance and
later campus modules remain planned.

## App boundaries (planned before initial models)

| App | Responsibility | Foundation |
| --- | --- | --- |
| accounts | Custom user, groups, authentication, role bootstrap | Implement |
| core | School settings, design system, dashboard routing, health | Implement |
| academics | Years, terms, classes, sections, subjects, teaching assignments | Models, lifecycle services and management UI |
| people | Student, guardian, teacher, staff profiles; enrollments and guardian links | Scoped reads, admissions/transitions, directories, imports and private images |
| audit | Append-only application event records and authentication signals | Implement |
| admissions | Applications, admission workflow and document review | Future |
| attendance | Dated registers, rules/calendar, corrections, leave, absence notices and scoped reports | Implemented |
| examinations | Assessment structures, Decimal marks, moderation, publication snapshots, report cards and analytics | Implemented |
| finance | Decimal invoices, fees, receipts, ledgers and reconciliation | Future |
| learning | Homework, assignments and submissions | Future |
| scheduling | Timetables, rooms and calendar events | Future |
| communications | Announcements and notification delivery | Future |
| hr | Employment records, leave and decimal payroll | Future |
| library | Titles, copies, members and loans | Future |
| transport | Routes, stops, vehicles and rider assignments | Future |
| inventory | Items, stock movements and custody | Future |
| certificates | Templates, authorized issuance and verification | Future |
| reporting | Permission-scoped operational and analytical read models | Future |

Only apps with implemented responsibilities are created. Future apps must not
import models across boundaries indirectly through UI code. Shared workflows
belong in explicit services inside the owning app; reads use scoped selectors.

## Access policy

Groups supply capabilities; selectors restrict which records those capabilities
apply to. Accounts may have multiple groups. Dashboard permissions never imply
access to all records. Student, guardian and teacher access is the union of their
explicit profile relationships. Administrative access requires a separate global
record permission. Unknown accounts fail closed. Object URLs query the already
scoped queryset and return 404 for inaccessible records. See PERMISSIONS.md.

Django admin is reserved for trusted system administrators (active superusers),
not for school roles. Model permissions alone do not bypass selector restrictions.
Adding write workflows requires applying the same scope to submitted foreign keys,
form querysets, service methods and exports, followed by negative access tests.

## Deployment boundary

Settings are split into base, development, test and production modules. Secrets
and database URLs come from environment variables. Test settings still require
PostgreSQL. Local demo data requires both DEBUG and explicit ALLOW_DEMO_DATA.
Render configuration is provided but deployment is not part of this work.
Production requires HTTPS, a trusted proxy, SMTP, private file storage, operational
monitoring, database backups and a separately reviewed authorization model.

## Phased implementation plan

1. **Foundation (implemented):** initial schemas and migrations, custom users,
   roles, sign-in/out/reset, scoped student reads, empty-state dashboards, security
   defaults, repeatable fictional seed, documentation and PostgreSQL tests.
2. **School operations (implemented):** validated admissions and enrollment workflows, guardian
   and staff management, academic setup UI, change history and access tests.
3. **Attendance (implemented):** daily student/staff registers, policies and calendars,
   audited corrections, employee leave, internal guardian notices and reports.
   Teacher marking is bounded by the assigned academic year and section.
   Timetable, homework, exams and results remain separate future work.
4. **Examinations (implemented):** configurable assessment/grade structures, conflict-checked
   date sheets, assigned-teacher marks, independent reviews, controlled publication,
   preserved report-card versions, personal portals, analytics and recommendations.
5. **Fees and finance (future):** immutable receipt references, decimal ledger
   workflows, approvals, reconciliation and notification delivery.
6. **Extended administration (future):** HR/payroll, library, transport, inventory and
   certificates with module-specific permissions and audit events.
7?10. **Further modules and commercial validation (future):** privacy and security review, retention policy,
   accessibility, PostgreSQL performance tests, restore drills, monitoring,
   incident procedures and deployment approval.

Each phase needs database constraints, scoped services, working UI, regression
tests and an updated IMPLEMENTATION_STATUS.md before being called complete.

Phase 2 services are in `academics/services.py`, `people/services.py`,
`people/directory_services.py` and `people/imports.py`. No separate admissions app
was needed for direct student admission; application/document review remains future
scope. PostgreSQL exclusion/unique constraints and a placement guard complement
service locking. CSV staging uses an owner-bound expiring `AdmissionImport` and an
explicit confirmation transaction. See [SCHOOL_OPERATIONS.md](SCHOOL_OPERATIONS.md).

Attendance keeps its owning services in `attendance/services.py`, scoped reads in
`selectors.py`, calendar evaluation in `calendar.py`, SQL aggregates in `reporting.py`
and bounded exports in `exports.py`. Academic/enrollment/profile transitions check
attendance references before changing date bounds. It reuses AcademicYear, Term,
Section, TeachingAssignment, Enrollment, Student, Guardian, Teacher and Staff rather
than introducing a second academic or people hierarchy. Transactional year locks
serialize roster, register, policy, leave and correction changes. Database guards
protect final rows, decisions, source relationships and notice history.


## Examination boundary

`examinations/services.py` owns setup, year-serialized roster/marks/review writes,
corrections, amendments, audit events and publication. `calculations.py` owns all
Decimal grading and explicit source-weight consolidation. `selectors.py` owns role,
teacher-subject and guardian/student scope; `reporting.py` exposes only permitted
current-publication aggregates. `exports.py` generates deterministic A4 PDFs from
immutable snapshots. Browser and PDF rendering use the same authorized records.

Assessment sessions contain section cohorts, subjects and weighted components.
Term/annual reports explicitly weight existing published sessions. Opening entry
freezes dated Enrollment references; no duplicate academic or people hierarchy is
introduced. PostgreSQL constraints, exclusions and guards complement transactional
services. PublishedResult and ResultPublication are append-only; approved corrections
and candidate amendments create fresh publication versions. Closed periods and
existing enrollment history remain protected. Recommendations feed the existing
school enrollment screen without automatically promoting students.

The current module boundaries and operating policy are in
[EXAMINATION_POLICY.md](EXAMINATION_POLICY.md). Phase 5 finance has not begun.
