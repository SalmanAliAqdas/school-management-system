# Implementation status

Phase 3 attendance management implemented and verified locally on 23 October 2026.
The existing Django/PostgreSQL architecture, authentication, administrator account,
academic setup, admissions and dashboards are retained.

## Completed attendance features

- Dated class/section/year registers with present, absent, late and excused statuses.
- Bulk present, individual adjustments, saved drafts, complete-roster final submission,
  optimistic versions, duplicate prevention and previous-record display.
- Enrollment-aware history across transfer, withdrawal and promotion; source dates
  cannot be changed to invalidate saved attendance.
- Versioned weekday/late/cutoff/excused/correction policies, term boundaries, holidays,
  school closures, additional working days and audited calendar cancellations.
- Original/revised correction history with mandatory reasons, independent reviewers,
  approval/rejection, timestamps and protected finalized records.
- Saved-data overview, daily/monthly charts, class comparisons, low attendance and
  separate missing/draft register lists. Missing attendance is never an absence.
- Student and linked-guardian summaries, monthly calendars, histories and downloads.
- Internal guardian absence notices with revision deduplication, supersession/read
  history, link-revocation checks and calendar-exclusion explanations.
- Separate teacher/staff registers, seven staff statuses, own/team dashboards,
  department reports, employment dates and canonical employee identity.
- Leave requests, independent approval/rejection, overlap prevention and explicit
  attendance correction history when an approval changes recorded staff attendance.
- Daily/weekly/monthly/year/custom reports; class/student/staff/department/absence/
  low-attendance views; authorized CSV, generated PDF and printable reports.
- Role/object/CSRF checks, bounded exports, CSV formula protection, audit events,
  database record guards and query-batched roster writes.
- Repeatable fictional weeks of attendance, holiday/closure, draft/missing register,
  low attendance, staff leave and correction examples without overwriting records.

## Module status

| Module | Status |
| --- | --- |
| Foundation authentication, roles and dashboards | Retained and regression tested |
| School branding and academic administration | Implemented; attendance-aware history guards added |
| Admissions, enrollments, guardians, teacher/staff profiles | Implemented and regression tested |
| Student and staff attendance | Implemented |
| Attendance calendar, corrections, notifications and leave | Implemented |
| Attendance reporting and CSV/PDF exports | Implemented |
| Examinations, results, fees, payroll, timetable, homework and other future modules | Pending; not started in this phase |
| Production hosting, durable storage, MFA, backup/restore and operational validation | Pending |

## Migrations

Six new first-party migrations applied to local PostgreSQL:

- people/0006: department, employment end dates and date constraints.
- attendance/0001: attendance models, indexes and constraints.
- attendance/0002: register, finalized entry, decision, policy and enrollment guards.
- attendance/0003: auditable calendar cancellation metadata.
- attendance/0004: calendar, employment and active-closure protection.
- attendance/0005: active notice uniqueness, notification history and future-date guards.

## Verification

- **185 automated PostgreSQL tests passed; zero failures/errors.** All earlier Phase 1/2
  regression coverage remains included. New tests cover permissions, boundaries,
  calculations, history, leave, notices, exports, concurrent writes and query scaling.
- Isolated installed-Chrome workflow test passed for four roles and eight screens at
  desktop/mobile sizes, including bulk present, draft/final submission, correction
  and leave review, guardian/student isolation, CSV and generated PDF.
- Django system/deployment checks, migration drift/pending checks, Ruff, installed
  dependency consistency and repository/identity secret checks passed.
- All account password/privilege fingerprints and existing student/enrollment counts
  remained unchanged. The original PostgreSQL database was preserved.
- See docs/VERIFICATION.md and docs/ATTENDANCE_POLICY.md for executed checks,
  policies, workflows, URLs and operating instructions.

## Remaining limitations and next phase

This is a functional prototype. Production-scale load, accessibility with assistive
technology, physical printing and multilingual PDF typography need acceptance testing.
Late/excused percentages use recorded opportunities and are not a statutory reporting
or payroll formula. Leave entitlement balances/cancellation, timetable/exam/fee/payroll
features and paid messaging providers are outside this phase. Used register identities
and finalized roster dates remain protected; exceptional register reversals require
separate audited design. Production storage, retention, backups, MFA and deployment
validation remain outstanding. No production deployment was performed.

The attendance foundation is ready for an explicitly authorized Phase 4; no later
phase has been started.
