# SchoolOS navigation

Start at `/`; sign-in uses `/accounts/login/` and sign-out is a POST form. The default
dashboard order is administration, teaching, student and guardian. A verified POST
workspace choice is remembered in the session and revalidated after role changes.

Administration retains academic setup, student/admission directories, attendance,
examinations, finance, school settings and audit links according to capabilities.
The roadmap describes future modules without granting operational access.

Student and guardian portals start at `/portals/student/` and `/portals/parent/`.
Open a child profile to reveal that child's attendance, results, report cards, fees
and calendar navigation. The guardian child selector retains the selected center.
The family overview offers direct actions for every authorized child and pagination.

Teachers start at `/portals/teacher/`. My classes provides year/subject/class search
and rosters; a class opens its limited student views and existing attendance/marks
workflows. Historical rosters have no attendance write action. Personal attendance
and leave link to their existing staff workflows.

All workspaces share `/portals/notifications/`, `/portals/settings/` and secure password
change. The bell displays the authorized unread count. Multi-role accounts can switch
only to dashboards whose capability they hold. Shared domain pages keep their own
server-side checks regardless of the sidebar currently displayed.

On mobile, Open navigation moves focus into the sidebar. Escape or Close navigation
restores focus to its toggle; Tab stays within the open sidebar. Skip to main content
bypasses repeated navigation. Charts provide expandable data alternatives and tables
scroll inside their cards. See [portal routes and policy](PHASE6_PORTALS.md).


## Teaching and communication

All workspaces now link to `/scheduling/`, `/learning/`, `/communications/calendar/`,
`/communications/` and `/communications/messages/`. The existing administration and
personal dashboards include actual lesson, assignment, event and conversation summaries.
`/modules/timetable/`, `/modules/homework/` and `/modules/announcements/` redirect to their
implemented workspaces. Timetable/workload and homework completion reports are linked
from their owning modules. The existing portal notification inbox includes separate
homework, timetable and school communication categories.

See [the Phase 7 route table](PHASE7_TEACHING.md#routes-and-navigation) for setup, reviews,
private submissions, moderation, access revocation and scoped downloads.
