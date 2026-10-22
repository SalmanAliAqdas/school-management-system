# Attendance management and policy

RumiWare SchoolOS records daily student attendance against dated enrollments and
employee attendance against existing teacher/staff profiles. This is the Phase 3
functional prototype; it does not calculate payroll or connect to messaging providers.

## Operating sequence

1. Configure an open academic year, its terms, sections and teacher assignments.
2. Open **Attendance > Policies & calendar** and add a policy effective from the
   beginning of the period to be recorded. Select working weekdays, late/cutoff
   times, late credit, excused treatment, correction window and low-attendance threshold.
3. Add public holidays, school holidays, unexpected closures or additional working
   days. Each exception has dates, a reason and a student/staff/both scope.
4. Open **Class register**, select the year, optional class, section and school date.
   Eligible students come from enrollment start/end dates, including historical
   placements. An inactive student is still eligible for dates before withdrawal.
5. Mark present, absent, late or excused. Arrival times determine present/late using
   the policy threshold. An excused absence needs a note. **Mark All Present** asks
   for confirmation, replaces draft statuses and clears arrival times; approved staff
   leave and closure statuses are preserved.
6. Save incomplete work as a draft. Review every student, check confirmation and
   finalize. A final register is immutable; later changes require approved corrections.

Staff registers use the same draft/final workflow with present, absent, late,
half-day, approved leave, official duty and school closure. Approved leave must
have an approved leave request. Closure status requires an active calendar closure.
An explicitly configured closure can have a staff register consisting of closure
rows; weekly holidays alone do not permit a staff register.

## Dates, calendars and cutoff

Attendance uses the IANA timezone in **School settings**, including the current
school date, cutoff and correction windows. Stored timestamps remain timezone aware.
Arrival inputs are local school times, not browser/device timestamps.

- Policy weekdays use Monday through Sunday. Unselected weekdays are weekly holidays.
- Holidays and closures override additional-working-day exceptions. If terms are
  configured and term enforcement is selected, student days outside those terms
  are excluded; without terms the academic year's date bounds apply. Staff use the
  year-wide working calendar, including office days between academic terms.
- Registers cannot be recorded in the future, outside the year, into a closed year,
  or for a person outside their enrollment/employment dates.
- Teachers must finalize by the cutoff on the register date. Administrators can
  submit later with a mandatory late-submission reason. Saving a draft does not
  publish it, notify guardians or count it in statistics.
- Dates with holidays/closures are excluded from statistics even if a register was
  finalized before the calendar exception was entered. Those original rows remain
  visible as retained records on the personal calendar.
- Calendar exceptions retain their original values. Authorized staff can cancel
  an erroneous exception with a reason; cancellation history is retained. Review
  previously recorded closure statuses when cancelling a closure.
- A policy referenced by any register is immutable. New revisions must start after
  all existing registers and affect later dates. Existing registers retain their
  original late/excused rules.

Closing an academic year requires its active enrollments to be resolved and draft
attendance registers to be finalized. Historical attendance prevents a backdated
transfer/exit or employment-date change from invalidating its source relationship.
Employee profiles with attendance require an end date when deactivated.

## Student percentage definition

Only finalized records on working school days contribute. For each contributing row:

| Status | Earned credit | Denominator |
| --- | --- | --- |
| Present | 1 | 1 |
| Absent | 0 | 1 |
| Late | Configured credit between 0 and 1; default 1 | 1 |
| Excused | 0 | 0 when excluded by policy; otherwise 1 |
| Draft, missing, holiday, closure or outside enrollment | 0 | 0 |

Percentage = 100 × earned credit ÷ recorded denominator, rounded to two decimal
places. No denominator displays **— / no recorded percentage**, not 0%.
Policies can change late/excused weighting for later registers without changing
the meaning of older rows. Reports combine the saved row weights.

For example, one present, one absent, one late with full credit and one excluded
excused day gives 2 ÷ 3 = **66.67%**. A missing register does not add an absence or
increase the denominator. Low-attendance reports compare recorded percentages to
the configured threshold and must be reviewed alongside unsubmitted registers.

Employee percentages count present, late and official duty as their applicable
credit, half-day as 0.5, and absent as zero. Approved leave and closure do not enter
the denominator. This is attendance reporting, not a salary or leave-balance formula.

## Corrections and leave approvals

Finalized attendance cannot be edited or deleted through ordinary forms, admin or
direct ORM updates. Teachers can request a correction within their assigned year/
section; employees can request corrections to their own attendance. Reasons are
mandatory. A different authorized reviewer must approve or reject; rejection also
requires a reason. Repeated or competing decisions cannot apply a change twice.

Each request retains original/revised status, arrival time, note, requester, reason,
request timestamp, decision, reviewer and decision timestamp. Approval checks the
original snapshot before applying the change and increments the attendance revision.
An outdated request cannot overwrite a subsequent correction. All decisions remain
in history, including rejections.

The normal window is configured in calendar days after the attendance date. The
window is checked both when requesting and deciding. Administrative roles have an
explicit historical-window override. Archived-year corrections require that override;
no correction reopens a finalized register or modifies its source enrollment.

Employees submit leave for themselves; authorized register managers can submit on
behalf of another employee. Dates must fit known employment and academic-year
bounds. Pending/approved leave requests cannot overlap for the same person. A
different authorized reviewer approves or rejects the request. Leave cancellation,
entitlement balances and payroll processing are future HR responsibilities.

Leave approval shows how many recorded entries it will change. A finalized entry
receives an explicit approved correction with original/revised values; drafts are
updated with a new version so stale forms cannot overwrite the approval. Approval
fails atomically if a pending correction or correction-window restriction prevents
an affected update. Existing closure rows remain closure rows.

Teacher and staff profiles remain independent of login accounts. When one account
has both profile types, its teacher profile is the canonical employee attendance
identity, avoiding two entries for the same account. Department and employment-date
fields prepare these records for a future HR module without creating payroll tables.

## Guardian notifications and privacy

Finalized absences create internal notices only for active, authorized guardian
accounts linked to that student. Drafts produce no notices. Notifications are unique
per guardian, entry and revision, with at most one active notice per guardian/entry.
Approved corrections supersede old notices and create a new notice when the revised
attendance is absent. Created/read/superseded timestamps and revision history remain.

Removing a guardian link or removing guardian permissions revokes access immediately,
including direct notice/report URLs. A guardian can select any linked child from the
attendance overview and can view only that child's permitted history and exports.
Notices do not include internal correction reasons or attendance notes. If a later
calendar exception excludes the day, the notice explains the calendar exclusion and
is presented as retained history rather than an active school-day absence.

Students see their own published attendance only. Teachers' student reads and writes
remain bounded by section/year assignments. Staff see their own records unless an
explicit staff-oversight capability grants wider access. Dashboard permissions alone
grant neither marking nor approval rights. CSV, PDF and printable routes use the
same selectors as interactive views.

## Screens and reports

| URL | Purpose |
| --- | --- |
| `/attendance/` | Student/teacher/guardian overview and authorized child selection |
| `/attendance/register/` | Student daily register selection, draft and final workflows |
| `/attendance/students/<uuid>/` | Student summary, monthly calendar and history |
| `/attendance/staff/` | Employee/department overview and own attendance links |
| `/attendance/staff/register/` | Staff daily register |
| `/attendance/employees/teacher/<id>/` | Teacher monthly attendance and leave history |
| `/attendance/employees/staff/<id>/` | Staff monthly attendance and leave history |
| `/attendance/corrections/` | Scoped correction history and review queue |
| `/attendance/leave/` | Scoped leave requests and decision history |
| `/attendance/leave/new/` | Leave submission |
| `/attendance/settings/` | Policy revisions and school calendar |
| `/attendance/notifications/` | Linked guardians' absence notice history |
| `/attendance/reports/<kind>/` | Filterable reports and authorized downloads |

Report kinds are `students`, `summary`, `classes`, `low`, `staff`, `staff-summary`,
`departments` and `staff-absences`. Select day, week, month, academic year or a custom
range. Filters include class/section/student or employee/department, status, name
search and sorting as applicable. Summary reports calculate across all statuses;
the staff absence report selects confirmed absent rows. Reports paginate HTML rows,
while exports/printing include all matching rows up to the 5,000-row limit. Choose
`format=csv`, `format=pdf` or `format=print`. Date ranges are limited to two years.

PDFs and printable pages use saved school branding; CSV cells neutralize spreadsheet
formula prefixes. Exports contain only the viewer's authorized rows. PDFs currently
use built-in ReportLab fonts; multilingual typography and physical-printer output
require additional acceptance testing.

## Demonstration and validation

`python manage.py seed_demo` retains the existing DEBUG/ALLOW_DEMO_DATA/password
gates. It appends several weeks of fictional attendance, holidays/closure, a draft,
a missing register, low attendance, staff attendance, approved/rejected/pending leave
and correction examples. Existing registers, profile fields and passwords are not
overwritten. Colliding/non-fictional employee/student identifiers are rejected;
mixed real/demo rosters are skipped. Repeat runs do not duplicate records or notices.

Automated tests exercise role/object scope, CSRF, enrollment/calendar boundaries,
draft/final transitions, database guards, percentages, leave, correction history,
notifications, reports, CSV/PDF output, concurrent writes and roster query scaling.
The browser harness creates a randomly named PostgreSQL test database, serves it on
loopback with installed Chrome and destroys only that newly created database:

```powershell
.\.venv\Scripts\python.exe scripts/attendance_browser.py
```

It verifies eight responsive screens and four roles, bulk present, draft/final
submission, correction/leave review, guardian/student isolation and downloads.
It requires a working date within the configured fictional demo year/terms. Local
screenshots are ignored under `.local/previews/attendance/`. See VERIFICATION.md
for executed results and implementation status for deployment limits.
