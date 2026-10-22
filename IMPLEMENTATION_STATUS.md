# Implementation status

Phase 4 examinations, results, grading and report cards implemented and verified
locally on 23 October 2026. The existing Django/PostgreSQL architecture,
authentication, administrator account and Phases 1?3 are retained.

## Completed Phase 4 features

- School-defined assessment types; dated year/term sessions with controllers,
  class/section cohorts, subject structures and theory/practical/other components.
- Explicit component/subject weights, maxima, passing thresholds, optional/exempt
  rules, contiguous custom grade bands, grade points and historical grading policies.
- Conflict-checked class/section/room/invigilator date sheets, school calendar checks,
  personal schedules and printable date sheets.
- Frozen dated enrollment rosters, assigned-teacher bulk/student-wise marks entry,
  student search, drafts, explicit missing statuses and submission/completion views.
- Decimal-only weighted calculations, configurable rounding, subject/overall passing,
  term/annual source consolidation and supplementary sessions preserving originals.
- Independent controller review/return/approval, configurable principal approval,
  explicit publication, archival, concurrency versions and attributed workflow events.
- Student/linked-guardian published result portals, selected-child performance charts,
  report history and complete withholding protection across historical personal URLs.
- School-branded A4 browser/PDF report cards with actual recorded approval, remarks,
  optional private photos/logos and immutable publication-time policy/identity/images.
- Independently approved marks corrections and remarks/visibility amendments that
  retain old report versions and issue revised publication snapshots.
- Scoped subject/class/section analytics, grade distributions, complete-record averages,
  pass percentages, academic support flags and opt-in private merit positions.
- Publication-bound promotion recommendations and reasoned overrides shown in the
  existing enrollment workflow; no automatic promotion or enrollment history changes.
- Permission-scoped internal submission/review/publication/correction notifications,
  de-duplication, safe CSV/PDF exports, filtering, sorting and pagination.
- Repeatable gated fictional midterm/final, draft/submitted/approved/published,
  absent/exempt/incomplete, remarks, rechecking and weighted term-report examples.

## Module status

| Module | Status |
| --- | --- |
| Foundation authentication, roles and dashboards | Retained and regression tested |
| School administration, admissions and academic operations | Retained and regression tested |
| Attendance, calendars, leave, corrections and guardian notices | Retained and regression tested |
| Examination setup, schedules and marks | Implemented |
| Grading, calculations, review and publication | Implemented |
| Result portals, report cards, corrections and analytics | Implemented |
| Optional ranking and promotion recommendations | Implemented; enrollment decisions remain explicit |
| Phase 5 fees and finance | Pending; not started |
| Later teaching/campus/HR/payroll modules | Pending; not started in Phase 4 |
| Production hosting and operational acceptance | Pending; no deployment performed |

## Database migrations

Five additive examination migrations applied successfully to local PostgreSQL:

1. `0001_initial`: examination schema, relationships, checks, unique/exclusion constraints.
2. `0002_history_guards`: roster, marks, setup/policy, decision and publication protection.
3. `0003_candidateamendment_examsession_retake_of_and_more`: independent candidate
   amendments, supplementary references and database grade-band overlap prevention.
4. `0004_amendment_schedule_guards`: controlled approved-candidate updates,
   schedule/invigilation identity protection and immutable recorded approval.
5. `0005_examnotification_exam_recipient_date_idx_and_more`: reporting indexes and
   valid marks-sheet state constraint.

Twenty-three new models reuse the existing people and academic hierarchy. No earlier
migration was removed. No local database was reset or recreated.

## Verification

- Baseline before implementation: **185 PostgreSQL tests passed** on `c716d27`.
- Final complete regression suite: **251 tests passed; zero failures/errors**.
  All Phase 1/2/3 tests remain included, with 66 examination tests covering calculations,
  grading/status boundaries, role/object restrictions, independent transitions,
  withholding, historical versions/images, amendments, concurrency, exports and queries.
- Installed headless Chrome workflow passed in a uniquely named isolated test database:
  administrator setup/scheduling, teacher draft/submission, controller review, principal
  approval, publication, correction/republication, student/guardian isolation, PDF/CSV
  and desktop/mobile screens. Only the owned browser test database was removed.
- Django system/production checks, migration drift/pending checks, Ruff lint/format,
  dependency consistency, static collection and repository/identity scans passed.
- Preservation fingerprints confirmed **all 431 original rows across 26 tables unchanged**,
  including account password/privilege fields and existing academic/people/attendance/
  audit records. The original administrator account and PostgreSQL database remain.
- Documentation: [examination policy](docs/EXAMINATION_POLICY.md),
  [implementation plan](docs/PHASE4_PLAN.md), [verification](docs/VERIFICATION.md).
  GitHub commit and workflow evidence are provided with the completion report.

## Remaining limitations and next phase

The requested Phase 4 prototype workflows are implemented. Before real-school use,
validate local grading/absence/promotion policy, production-scale load, assistive
technology, physical printing, multilingual PDF fonts and operational privacy controls.
Marks entry is bounded to 1,500 candidates per sheet; report exports/analytics to
5,000 results. Class schedule conflict protection is conservative across sections.
Published term/annual reports intentionally retain captured source versions; source
corrections do not silently rewrite issued consolidations. Archived sessions remain
protected. No verified digital signatures, paid messaging, fees, finance or payroll
were added. Production storage, retention, MFA, backup/restore and hosting validation
remain outstanding. Phase 5 is ready for explicit authorization after review; it has
not been started.
