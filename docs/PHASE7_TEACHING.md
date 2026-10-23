# Teaching, learning and communication

Phase 7 adds server-rendered scheduling, learning and communication workflows to
SchoolOS. Existing academic identities, attendance calendars, examination results,
financial journals and personal portals remain authoritative.

## Routes and navigation

| Route | Workspace |
| --- | --- |
| `/scheduling/` | Today's lessons and available timetable versions |
| `/scheduling/new/` | Timetable draft |
| `/scheduling/setup/periods/` | Year, weekday, shift, period times and breaks |
| `/scheduling/setup/rooms/` | Classrooms, laboratories and other spaces |
| `/scheduling/setup/availability/` | Unavailable, available or preferred teacher periods |
| `/scheduling/setup/limits/` | Daily and weekly workload limits |
| `/scheduling/<id>/` | Weekly grid, publication, copy, archive and completeness |
| `/scheduling/reports/` | Workload, free periods, room usage, substitutions and assignment access |
| `/scheduling/duties/<id>/` | Approved substitute's roster on the exact duty date |
| `/learning/` | Searchable homework with linked-child filtering |
| `/learning/new/` | Assigned-teacher homework creation |
| `/learning/<id>/` | Instructions, submission versions and permitted feedback |
| `/learning/<id>/submit/` | Student draft/final submission and attachments |
| `/learning/submissions/<id>/review/` | Teacher feedback, grading and release |
| `/learning/reports/` | Completion, late/missing/reviewed/excused counts |
| `/communications/` | Audience-scoped events and announcements |
| `/communications/calendar/` | Combined calendar with child selection |
| `/communications/messages/` | Searchable, paginated private conversations |
| `/communications/messages/new/` | Child context and eligible recipient selection |
| `/communications/moderation/` | Reported messages and reasoned decisions |
| `/communications/policy/` | Approval, message limits and minimum retention |
| `/portals/notifications/` | Existing notices plus homework, timetable and communication categories |

All changes use POST and CSRF protection. Downloads repeat object authorization.
Existing dashboards and portal navigation link to these workspaces. A selected
personal portal narrows its dashboard summaries even for users with other roles.

## Timetable operation

Create periods for an academic year and shift. Each period has a weekday, start,
end and type: lesson, break, lunch or assembly. Rooms have a type and availability
flag. Teacher assignments reuse the existing year, section, subject and teacher.

Create a dated version, optionally within a term, then allocate lessons. Entries
must use compatible academic years, active rooms and employed teachers. Validation
checks overlapping teacher, room and section/cohort allocations, unavailable
teacher periods, approved staff leave, non-teaching periods and version dates.
School calendar closures and non-working dates are omitted from occurrences.
Where no attendance policy exists, the explicitly configured period weekday is used.

A school-level PostgreSQL transaction advisory lock serializes schedule edits and
publication. Draft revision numbers reject stale edits. Publication materializes
bounded dated bookings; exclusion constraints reject overlapping teacher, room and
section time ranges. Published lessons and used periods are protected by database
triggers. Archive a superseded version before publishing an overlapping replacement.
Copying preserves the original version and creates an editable draft.

The suggestions screen checks individual teacher/room options against the same
validator. It does not claim global optimization. Workload limits produce warnings;
reports show actual weekly allocations, free configured periods and booked room
occurrences. Completeness compares configured lesson periods with represented
sections; it is not a curriculum-hours optimizer.

Substitutions preserve the original entry, date, substitute, reason and state.
The substitute must have a relevant subject assignment, valid employment, no
approved leave and no simultaneous lesson or substitution. Approval changes the
resource booking and notifies affected users. The temporary roster requires the
approved teacher, the exact school date and a published timetable. It exposes names
and roll numbers only; it grants no marks, finance, report-card or permanent access.

Teaching-assignment access can be revoked without deleting referenced history.
The active assignment manager is used by existing teacher selectors; the attendance
section join also explicitly requires active assignments. Historical foreign keys
remain resolvable through the unfiltered base manager. Access decisions retain actor,
reason and state. Existing year/employment bounds still apply.

## Assignment lifecycle

Teachers create work only for current authorized assignments. Oversight requires
`learning.manage_learning`. Drafts stay private. Publishing schedules visibility at
`publish_at`; no worker is required. Due dates and late policy determine whether
submissions remain open. Authorized actions close, reopen or archive work.

Assignments support text instructions, configured type choices, optional supporting
files, completion-only work, marks, rubric criteria and a percentage late penalty.
Rubric maxima must equal the assignment maximum. Homework marks never write into
published examination results or official report cards.

Material instruction/deadline edits create an attributed snapshot and notification.
After submissions exist, teaching identity, original publication date, grading
maximum/rubric, penalty and submission requirements are frozen. Closed and archived
work cannot be edited through the ordinary editor. Teachers cannot indefinitely
edit historical academic years.

Student eligibility requires the original dated enrollment and a current matching
placement. Guardians can monitor linked children but cannot submit for them. Every
save creates a new immutable submission version. Final work cannot be overwritten;
a released revision request enables another version. Earlier text and files remain
available under current authorization. Missing status begins only after the deadline.

Feedback revisions are append-only. Private review comments are hidden until explicit
release. Guardian visibility is a separate opt-in. Marks are bounded by the maximum;
rubric totals and configured late deductions are validated. Exemptions have reasons
and are excluded from completion denominators. CSV exports are teacher/oversight
scoped and protect spreadsheet formula prefixes in student identifiers.

## Private attachments

Learning attachments allow up to five files per supporting set or submission version;
messages allow three. Each file is limited to 5 MB. Allowed formats are PDF, UTF-8
text, PNG and JPEG. Extension, declared type and content checks are applied; images
are decoded for verification. PDF checks are structural signature checks, not a
malware scan. Filenames are normalized and stripped of unsafe characters.

Bytes are stored in PostgreSQL binary fields with their protected source references.
There is no public media URL. Downloads require the current assignment, submission,
publication or conversation scope and use attachment disposition, no-store caching
and nosniff. Original documents and submitted versions are immutable. No malware
scanner or external file provider is claimed. Capacity, malware scanning and durable
backup policies require a separate production operational review.

## Events, announcements and calendar

Events and announcements share targeted publication controls while retaining distinct
kinds. Audiences include school, administrators, staff, teachers, students and guardians,
optionally restricted to an academic year and section. Class targeting is achieved by
publishing to its sections. Events contain ordered start/end timestamps, organizer,
location and category. Announcements support pinning, importance, expiry and attachments.

Approval is independent by default. An authorized publisher may change the policy
explicitly; authors cannot silently bypass its gate. Scheduled publications become
visible at their publication time without background jobs. Changes retain history;
cancellation requires a reason and remains visible to the authorized audience.

The combined calendar reads published events, homework deadlines, examination dates,
term boundaries, attendance holidays and a bounded seven-day lesson preview. School
settings supply the timezone for operations forms and rendered dates. An informational
event never creates an attendance closure or changes attendance denominators. Use the
existing attendance calendar workflow for actual closures. Recurrence generation is
not included; date-bounded timetable occurrences are the only materialized recurrence.

## Conversations and moderation

A family thread requires a current guardian link, current enrollment and a currently
authorized teacher assignment. Administrative school communicators may contact linked
families. Staff-to-staff threads require active staff capabilities. Students cannot
open arbitrary adult or public conversations. The recipient selector and write service
both enforce eligibility; saved thread membership alone grants no lasting access.

Thread reads, replies, notices and attachments recheck current relationships. Revoked
links, inactive assignments, expired employment and removed roles withdraw access.
Messages preserve sender, body and timestamp. Read state and moderator visibility can
change; original message content cannot be rewritten or deleted. Text uses Django
escaping and is not rendered as HTML or auto-linked unsafe markup.

Sending locks the sender account before checking the configured hourly rate limit.
Duplicate text to the same thread within one minute is rejected. Participants may
report a message. Only explicit moderators can inspect reports and issue a single
reasoned decision, hide the reported message or block further replies. Moderators do
not receive an unrestricted searchable inbox of all private messages.

Retention defaults to a minimum of 2,555 days. The setting records policy; no automatic
purge runs. Legal holds, disposition approvals and backup retention are operational
responsibilities. There is no unrestricted deletion endpoint.

## Notices and operational boundaries

Attendance, examination and finance notices retain their existing sources. New notices
use unique recipient/action keys and deep links. Homework publication, updates, due-soon,
feedback/revision, timetable publication/substitution, events/cancellation, announcements
and messages are included. Due reminders are hidden when obsolete, completed or past due.
Visibility is evaluated on every read, including current publication timing and family
relationships. Reading remains an explicit scoped POST action.

The implementation uses Django, PostgreSQL and local browser assets. It adds no paid
messaging service, external chat, worker broker or production deployment. Messaging uses
ordinary refresh and form submission. Scheduling assistance is advisory; multi-school
operation, large-volume capacity tuning, automated retention disposal and deployment
hardening are outside this phase. Phase 8 modules are not implemented.

## Verification and preservation

Run the full PostgreSQL suite and both `scripts/phase7_browser.py` and
`scripts/portal_browser.py`. Browser scripts create random, owned test databases,
use fictional identities, save ignored screenshots under `.local/previews/` and
remove their databases/servers in teardown. They never seed the original school.

The Phase 7 preservation baseline contains 2,654 rows across 99 original tables.
The preservation checker records hashes, original column names and hashes of schema
metadata rows, without exporting row contents. Post-upgrade verification requires all
original values to remain identical. Only additive migration/content-type/permission
metadata is permitted with the explicit schema-addition check; new app tables and the
assignment active flag are additive. See [verification evidence](VERIFICATION.md).
