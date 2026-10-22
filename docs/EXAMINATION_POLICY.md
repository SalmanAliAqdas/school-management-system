# Examination and grading policy

Phase 4 uses the existing academic years, terms, sections, subjects, teaching
assignments and dated enrollments. All example identities and marks are fictional.
This prototype requires school acceptance and operational validation before real use.

## Setup and configuration

1. Synchronize roles after migrations with `python manage.py sync_roles`.
2. Under Examinations → Configuration, create assessment types and an academic-year
   grading policy. Types are school defined: tests, midterms, finals, practicals,
   oral assessments, coursework and supplementary assessments are all supported.
3. Add grade bands covering 0–100 contiguously. Lower bounds are inclusive and upper
   bounds exclusive, except that the final band's upper bound includes 100. Gaps,
   overlaps and out-of-range values are invalid. Labels, descriptions and optional
   grade points are configurable; the demo scale is an example, not a mandatory rule.
4. Create a session with year, optional matching term, dates, eligibility date, type,
   policy and description. Add explicit controllers, class/section cohorts, subjects
   and assessment components. A subject must already belong to the class/year.
5. Subject weights in each cohort and assessment weights within each subject must
   each total **exactly 100%**. All components, including optional ones, participate
   in configuration validation. Incorrect weights are never silently normalized.
6. Configure each component's maximum, weight, passing percentage, required-pass flag
   and theory/practical/oral/coursework/other classification. Configure subject passing
   percentages and required subjects, plus overall passing and subject-pass policy.

Opening entry freezes the roster and setup. Reuse a policy for compatible sessions;
create a new named policy version to change used rules. Used policies, bands,
assessment structures, eligibility references and approved remarks are protected.

## Schedules and eligibility

Date sheets use the school timezone. Slots must be ordered times on one school date
inside the examination window. Configured attendance holidays, weekly holidays,
closures, working exceptions and term rules are checked without changing attendance.
When no attendance policy exists, the examination window still applies.

PostgreSQL exclusions prevent overlapping slots for the same class, section, room
or invigilator. Class protection is conservative: sections of one class cannot be
scheduled concurrently. Adjacent slots may touch without overlapping. A room and
invigilators are optional. Invigilation dates must match the slot. Schedules can be
revised during setup/entry until any sheet is submitted; submitted schedules freeze.

The explicitly configured eligibility date determines enrollment eligibility. Opening
entry creates one candidate per student/session from the matching dated enrollment,
including historical placements. A transfer after that date preserves the original
candidate and marks. Enrollment edits cannot invalidate a frozen eligibility date.
The eligibility date is a school rule, not an assumption about current enrollment.

Supplementary sessions reference a previously published original assessment in the
same year, start after it ends, and admit only original candidates who also satisfy
the new dated enrollment roster. Original results remain intact. Consolidations
explicitly choose the original or the supplementary replacement; they cannot count
both as separate contributions. No automatic best-score substitution is inferred.

## Marks and status rules

Marks use Decimal arithmetic, up to three fractional places, with 0 ≤ mark ≤ maximum.
Present/assessed rows require a numeric mark. Every other status requires empty marks.
Exempt and withheld assessment rows require an explanation. Only examination oversight
staff can withhold. Bulk entry posts the exact frozen roster with optimistic versions;
duplicate, forged, missing or stale rows fail atomically. The supported entry size is
1,500 candidates per sheet. Search narrows visible rows while retaining the full roster.

| Status | Default effect | Configuration |
| --- | --- | --- |
| Assessed | Numeric credit / configured maximum | Component weight and pass threshold |
| Absent | Incomplete, no invented mark or percentage | Explicit policy may assign zero credit; status stays absent |
| Exempt | Exclude that assessment's weight and raw maximum | Policy may require academic review instead |
| Pending | Incomplete | Optional pending components may be explicitly excluded |
| Incomplete | No complete percentage or grade | Must be resolved through the appropriate workflow |
| Withheld | Entire report's marks, grades, remarks and ranking are restricted | Independent correction/amendment controls release |

Pending/incomplete statuses may be submitted for review as explicit declarations.
Their presence never fabricates a zero. A reviewer can return the sheet with reasons.
A wholly exempt subject has no numeric percentage; an entirely exempt report needs
academic review and has no invented overall percentage.

## Calculations and passing

For each counted assessment:

`assessment_percentage = marks / maximum × 100`

`subject_percentage = Σ(assessment_percentage × weight) / Σ(counted weight)`

Only exclusions explicitly authorized by exemption/optional policy remove weights.
An included missing/incomplete status makes the subject incomplete. A required-pass
component below its passing percentage fails that subject even if the weighted
subject percentage is high. Subject passing also checks the configured subject threshold.

`overall_percentage = Σ(subject_percentage × subject weight) / Σ(counted subject weight)`

Included incomplete subjects prevent an overall percentage. Overall passing requires
the configured overall threshold and, when enabled, passing all required subjects.
Raw obtained/maximum totals are shown separately from weighted percentages; raw marks
and weighted percentages need not produce the same number. Comparisons and grades
use **unrounded Decimal values**. Display rounds half up to the policy's 0–3 places:
49.999 may display 50.00 while remaining below a 50 passing boundary.

Term/annual sessions use explicitly weighted published source sessions totaling 100%.
Term sources must be assessment sessions from that term; annual reports may use
assessment or term sessions from the same year. Each source covers the report's sections.
Subject percentages are weighted across sources, then evaluated under the report's
saved subject/overall criteria. Consolidated subject credit is expressed out of 100;
the breakdown identifies the exact source publications. Missing source information
remains incomplete. Later source corrections never silently rewrite a published
consolidation; a newly reviewed report is needed to capture newer source versions.

## Review, publication and history

1. Teachers save draft marks and submit sheets for review only for their explicitly
   assigned academic year, section and subject. Drafts remain private to authorized staff.
2. An explicitly assigned controller or global oversight reviewer starts review,
   returns the sheet with reasons or approves it. Independent review is enabled by
   default and rejects review of the actor's own submission.
3. Authorized staff close entry, then submit the completed examination for final review.
   Every assessment sheet must have controller approval. Returned work requires reopening
   entry and resubmission; approval never bypasses missing controller reviews.
4. The configured principal gate requires final-approval permission. If disabled,
   an authorized session reviewer may approve. Independent submission checks still apply;
   consolidated reports require a different final approver from their submitting reviewer.
5. A publisher explicitly confirms publication after the window ends. Atomic version
   checks prevent duplicate publication. Students/guardians see only published/archived
   permitted reports; they never see drafts or review previews.
6. Published sessions may be archived. Closed academic periods reject new examination
   writes; unfinished sessions must be resolved before academic closure.

Each publication stores append-only candidate snapshots with policy/bands, component
marks, percentages, outcomes, remarks, source versions, rankings, school identity,
issue timezone and bounded image bytes. Old report cards remain reproducible after
school/student images or profile values change. PDF generation is deterministic for
an unchanged snapshot. Approval names reflect recorded actors; no digital signature,
official seal or handwritten approval is invented.

An approved mark requires a reasoned correction request with original/proposed values.
A different authorized reviewer approves or rejects it. Approval applies the exact
checked revision and issues a new complete publication for a published session.
Previous snapshots remain unchanged, with visible version history and current-version
indicators. Remarks and result withholding/release use the same independent amendment
pattern. While the latest result is withheld, older versions are also blocked from
student/guardian HTML, image and PDF access. Restricted marks do not enter portal
charts, CSV output or publication notifications. Archived sessions remain protected.

## Access, analytics, recommendations and notifications

- System/school administrators and principals have explicit examination oversight.
  Only system administrators/principals receive the principal approval capability.
- Examination controllers are scoped to explicit session assignments. They cannot
  grant themselves access to another session through setup foreign keys or sources.
- Teachers see/enter assigned subjects; their analytics contain only assigned-subject
  aggregates, without other subjects or overall student report cards.
- Students see their own published reports. Guardians see only currently linked
  children and can select one child's historical chart. Unlinking immediately revokes
  reads, exports, images and notices, including old URLs.
- Other staff dashboard roles receive no examination access by default.
- Analytics use current publication versions and real complete records, with separate
  incomplete counts. Withheld and incomplete rows never enter averages/pass-rate
  denominators. Tables show counts and avoid speculative rankings. The support
  threshold is configurable; failure and incomplete reports are also flagged.
- Ranking is disabled by default. When enabled it uses complete published results,
  optional passing-only eligibility, class/section scope and competition or dense ties.
  A personal report shows only that student's position, never the class ranking list.
- Promotion recommendations check overall and required-subject passing criteria.
  Authorized reasoned overrides are append-only and tied to a publication version.
  The existing enrollment-change screen displays published evidence and current-version
  overrides. Recommendations never automatically promote or alter enrollment history.
- Internal notices cover submission, review, returns, approval, publication and
  corrections/amendments. Recipient/event/candidate uniqueness prevents duplicates.
  Access is rechecked on reads; notices contain no restricted marks or private reasons.
  No paid messaging or external delivery service is enabled.

## Screens and operation

| URL | Purpose |
| --- | --- |
| `/examinations/` | Scoped examination dashboard and selected-child performance |
| `/examinations/setup/<kind>/` | Types, rooms, policies, bands, sessions, cohorts, subjects, assessments, controllers, sources, settings |
| `/examinations/sessions/<uuid>/` | Structure, completion, review controls, candidate list and audit history |
| `/examinations/sessions/<uuid>/schedule/` | Conflict-checked date-sheet editing |
| `/examinations/schedules/` | Authorized schedules and browser printing |
| `/examinations/marks/<id>/` | Draft/submitted class/subject marks; student search |
| `/examinations/marks/<id>/review/` | Controller review/return/approval |
| `/examinations/candidates/<uuid>/` | Staff preview, remarks, issued versions and recommendations |
| `/examinations/results/` | Current published reports, filters, sorting, pagination and CSV |
| `/examinations/reports/<uuid>/` | Authorized A4 preview and version history; `?format=pdf` download |
| `/examinations/corrections/` | Marks corrections and candidate amendments |
| `/examinations/sessions/<uuid>/analytics/` | Permitted class/section/subject analysis |
| `/examinations/notifications/` | Current-access internal updates and POST read acknowledgement |

Writes use POST/CSRF with server-side capability/object checks. GET confirmation pages
do not mutate records. Exports are authorized and bounded to 5,000 results; CSV cells
are formula-escaped and PDF text XML-escaped. Images reuse sanitized private uploads
and snapshot-scoped delivery; no external image URL is fetched. Django admin remains
read-only for examination records and restricted to trusted system administrators.

`seed_demo` remains development-only, explicitly gated by DEBUG, ALLOW_DEMO_DATA and
the locally supplied DEMO_PASSWORD. It appends known fictional examination types,
weighted midterm/final examples, schedules, draft/submitted/approved/published marks,
absence/exemption/incomplete examples, remarks, rechecking and a term consolidation.
It declines mixed real/demo rosters and never overwrites existing sessions, results
or account passwords. Re-running preserves published versions and existing records.

## Verification and operating limits

See [verification evidence](VERIFICATION.md) and [the Phase 4 plan](PHASE4_PLAN.md).
The automated suite covers calculation boundaries, role/object denials, publication
confidentiality, database guards, history, concurrency, exports, query bounds and
regression of earlier phases. `scripts/examination_browser.py` exercises the complete
workflow in its own uniquely named disposable test database using installed Chrome.

Real-school policy acceptance, large-cohort load, assistive technology, physical
printing and multilingual PDF fonts still need validation. There are no statutory
grading claims, verified digital signatures, paid notifications or production hosting.
Fees, finance and later phases have not been started.
