# Phase 6: everyday school portals

SchoolOS provides three server-rendered workspaces over its existing Django and
PostgreSQL modules. This phase adds no business models or migrations, authentication
system, frontend framework, hosted service or paid provider.

## Entry points and navigation

| URL | Purpose |
| --- | --- |
| `/portals/student/` | Personal attendance, published performance, balance and documents |
| `/portals/parent/` | Paginated family overview, one summary per currently linked child |
| `/portals/teacher/` | Assigned-class registers, assessment work, personal attendance and leave |
| `/portals/<role>/students/<student-uuid>/profile/` | Read-only academic identity and enrollment history |
| `/portals/<role>/students/<student-uuid>/attendance/` | Monthly calendar, policy-based statistics and trend |
| `/portals/<role>/students/<student-uuid>/results/` | Latest authorized published results and configured upcoming exams |
| `/portals/<role>/students/<student-uuid>/reports/` | Authorized issued report versions and PDF links |
| `/portals/<role>/students/<student-uuid>/fees/` | Issued invoices, allocations, separate balances, receipts and statement links |
| `/portals/<role>/students/<student-uuid>/calendar/` | Existing term dates, holidays, exam slots and invoice due dates |
| `/portals/parent/select-child/` | Validated child switch retaining the selected center |
| `/portals/teacher/classes/` | Year-filtered class/section/subject search |
| `/portals/teacher/classes/<assignment-id>/` | Scoped, searchable and paginated student roster and assessment links |
| `/portals/teacher/classes/<assignment-id>/students/<student-uuid>/` | Limited academic and attendance view |
| `/portals/notifications/` | Unified filtered, paginated source notification inbox |
| `/portals/notifications/<category>/<notice-id>/read/` | POST-only authorized source read-state update |
| `/portals/settings/` | Contact phone, account information and session display spacing |
| `/portals/settings/password/` | Django validated password change with session hash rotation |
| `/portals/switch/` | POST-only switch between explicitly authorized dashboards |

Personal `<role>` values are `student` and `parent`; teacher student records use the
assignment routes. Existing `/dashboard/student/`, `/dashboard/parent/` and
`/dashboard/teacher/` bookmarks render these workspaces. `/` retains its original
default role order and honors a still-authorized selected workspace preference.
Existing domain URLs remain the destinations for register/marks writes, corrections,
leave, report details, PDFs, invoice details, receipts and statements.

The school identity, private logo, top navigation, bell, focus styles and role-specific
sidebar are shared. There are no timetable, homework or chat placeholders in portal
navigation. Mobile navigation supports Enter, Tab and Escape with focus restoration.
Charts have a text data alternative and do not animate. Wide tables scroll within
their containers. Display spacing is a session preference.

## Student experience

The overview shows the attached student, private photograph where available,
admission number, current dated enrollment, today's finalized attendance, monthly
attendance percentage, latest published grade, authorized receivable and recent
invoice/report links. Missing attendance says **Not recorded**. Unavailable
attendance percentages and policy-disabled finance say **Unavailable**, never zero.

The profile includes subjects, configured subject teachers, a minimal guardian
summary, school contact information and enrollment history without administrative
notes. Official identity and enrollment fields are read-only. There is no dedicated
class-teacher model in the existing schema; the portal does not infer a class teacher
from a subject assignment.

Attendance uses Phase 3 `report_rows`, `summary`, `monthly_trends`, `SchoolCalendar`
and `month_cells`. Late credit, excused-day exclusion, closures and missing-register
rules remain in those services. Historical years are selectable; downloads go through
the existing scoped attendance export workflow.

Results use Phase 4 publication snapshots and current-publication selectors. Pending,
absent, exempt and incomplete statuses remain explicit in the existing report detail.
Current withholding suppresses personal summary/results and historical report links;
existing report/PDF routes independently repeat their authorization. Corrected versions
remain available after an authorized release. Progress charts use published complete
percentages without combining incompatible grading policies into a new average.

Finance uses Phase 5 control balances and invoice allocation/release calculations.
Receivables, advance, funded refundable deposit and uncollected deposit remain separate.
Currency precision follows finance configuration. Receipts preserve reversal overlays
through the original detail/PDF workflow. No journals or posting actions are exposed.

## Guardian experience

A page contains up to twelve linked-child summaries, with pagination for larger
families. The child selector preserves the current profile/attendance/results/reports/
fees/calendar center. Every target UUID is resolved again through current guardian
links on every request; the browser's selection is never an authorization grant.

Each child has separate account balances, reports, attendance and timeline. No family
money total is introduced. Other guardians' contact details are not exposed through
the guardian profile summary. Child-related inbox links include an authorized child
filter. Deleting a link immediately revokes current/historical centers, source notices,
report PDFs and finance documents unless another independent permission permits access.

## Teacher experience and dates

The workspace selects the teacher's own year/section/subject assignments, including
for users who also have administrative capabilities. Search and year filters cannot
expand this scope. Current rosters use dated enrollment intervals. Historical rosters
are deduplicated by student and require teacher employment overlap.

Today’s work distinguishes missing, draft and finalized registers and calendar
exclusions. Assessment queues show actual sheet state and saved-status completion
against eligible candidates. Register and marks actions call the original services;
controller/principal approval, optimistic versions, exact rosters and database guards
remain active. Submitted-register history, subject analytics, personal staff attendance
and pending/approved leave reuse the existing module workflows.

The original TeachingAssignment has **no independent start/end dates**. Its scope is
academic year + section + subject. The portal additionally respects teacher employment
dates; it cannot invent a finer appointment history. Historical assignments are
read-only. Attendance/marks write services and entry forms now require an open year
containing today and a currently employed active teacher, unless the existing global
domain oversight capability applies. Attendance also checks employment on the recorded
date. This closes direct-URL writes as well as hiding historical write actions.

The limited student view projects only the assigned subject from current published
snapshots and finalized attendance in the assignment/employment interval. It excludes
family contacts, finance, private administrative notes and unrelated subject results.

## Shared notifications and account policy

`portals/notifications.py` uses a SQL union of scoped attendance, examination and
finance source projections for global ordering, category/unread/child filtering and
pagination. Only the current page is hydrated. There is no inbox-copy model, migration,
page-load notification generation or cache. Original source read states and histories
remain authoritative. The bell counts authorized unread source rows. Display times
use the configured school timezone.

Mark-read resolves the category from a fixed allowlist, checks the scoped source row,
then repeats the scoped filter in the update. Guessed IDs and revoked relationships
fail closed. All mutations are POST/CSRF protected. Deep links repeat the owning
module's object checks. Superseded attendance notices retain their source status.

Only linked contact-profile phone fields and an allowlisted session display preference
are editable. Official names, enrollment fields, usernames, privilege flags and email
are not accepted by these forms. Email changes require school-office identity and
address verification through the administrative process; no unverified self-service
email change is introduced. Password changes use Django's current-password check,
password validators and `update_session_auth_hash`. Existing reset, throttling,
POST logout, session and private-response protections remain in use.

## Queries, bounds and extension points

Child summaries use batched enrollment/attendance/publication/finance queries.
Finance owns the grouped control-balance and allocation/release reads; invoice status
calculation is shared with the original single-invoice service. Query-budget tests
compare one and multiple children/classes. Source notices are paginated by SQL rather
than loading every historical notice into Python.

Bounded previews include 40 assignment rows, 8 pending dashboard marks sheets and 6 published class summaries, 6 recent
registers, 5 leave entries, 30 recent payments, 100 academic chart points and up to
150 exam/invoice calendar items per source. Complete history/search remains available
through the linked domain registers and paginated centers. The compact child selector
contains up to 100 children; larger families use the paginated family overview.

`calendar_items` composes existing term, attendance-calendar, exam-schedule and issued
invoice sources. Future timetable/homework/event adapters can join this read layer
after their own authorization models exist. There is no weekly timetable, homework,
two-way messaging, gateway, payroll, library, transport or inventory implementation.

## Fictional demonstrations and operational limits

`seed_demo` remains DEBUG + ALLOW_DEMO_DATA gated and requires a locally supplied
password. Phase 6 reuses the same students, two-child guardian, paid/overdue invoices,
incomplete results and draft marks. It adds an assignment to the existing draft-register
section and a separate fictional historical year/enrollments through open → closed →
archived lifecycle actions. Repeated runs preserve passwords, administrator flags,
issued finance transactions and historical records. The original database is not
automatically seeded during implementation or browsing.

This is a development prototype. Real-school privacy acceptance, operational backups,
load testing, assistive-technology audit, durable private storage, multilingual document
review and independent commercial security validation remain necessary. Phase 7 can
extend the read layer; none of its features are represented as already implemented.

See [verification](VERIFICATION.md), [permissions](PERMISSIONS.md),
[security](SECURITY.md) and [navigation](NAVIGATION.md).
