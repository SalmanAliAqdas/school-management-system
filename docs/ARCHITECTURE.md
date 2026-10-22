# RumiWare SchoolOS architecture

## Scope and decisions

SchoolOS is a single-school modular Django monolith. Django templates, Bootstrap 5,
local CSS, and small JavaScript modules provide the interface. PostgreSQL is the
application and test database. Django 5.2 LTS and Python 3.12–3.14 are the supported
baseline. No separate API server, job broker, or frontend build tool is required.

Foundation scope is authentication, access policy, school configuration, academic
and profile relationships, read-only student access, audit events, and dashboard
shells. The future operational modules are not represented as completed features.

## App boundaries (planned before initial models)

| App | Responsibility | Foundation |
| --- | --- | --- |
| accounts | Custom user, groups, authentication, role bootstrap | Implement |
| core | School settings, design system, dashboard routing, health | Implement |
| academics | Years, terms, classes, sections, subjects, teaching assignments | Schema and admin |
| people | Student, guardian, teacher, staff profiles; enrollments and guardian links | Schema, scoped read views and admin |
| audit | Append-only application event records and authentication signals | Implement |
| admissions | Applications, admission workflow and document review | Future |
| attendance | Dated student and staff attendance against enrollments | Future |
| examinations | Exams, assessments, decimal marks, moderation and results | Future |
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

1. **Foundation (this delivery):** initial schemas and migrations, custom users,
   roles, sign-in/out/reset, scoped student reads, empty-state dashboards, security
   defaults, repeatable fictional seed, documentation and PostgreSQL tests.
2. **School operations:** validated admissions and enrollment workflows, guardian
   and staff management, academic setup UI, change history and access tests.
3. **Teaching:** attendance, timetable, homework, exams and moderated results.
   Every teacher action is bounded by an assigned class and subject.
4. **Finance and communication:** immutable receipt references, decimal ledger
   workflows, approvals, reconciliation and notification delivery.
5. **Extended administration:** HR/payroll, library, transport, inventory and
   certificates with module-specific permissions and audit events.
6. **Commercial validation:** privacy and security review, retention policy,
   accessibility, PostgreSQL performance tests, restore drills, monitoring,
   incident procedures and deployment approval.

Each phase needs database constraints, scoped services, working UI, regression
tests and an updated IMPLEMENTATION_STATUS.md before being called complete.
