# Phase 4 implementation plan

Baseline: `c716d27`, clean working tree, matching public main, 185 PostgreSQL tests
passing before changes. Existing database rows have private preservation fingerprints.

1. Reuse AcademicYear, Term, Section, Subject, ClassSubject, TeachingAssignment,
   Enrollment, Student, Guardian and Teacher in a new examinations application.
2. Configure named assessment types and versioned grading policies with contiguous
   bands, explicit absence/exemption rules, passing criteria and Decimal rounding.
3. Model examination sessions, section cohorts, subject structures and weighted
   theory/practical/other assessments. Term/annual sessions explicitly weight
   published source sessions; never infer weights or normalize invalid totals.
4. Freeze dated enrollment rosters when marks entry opens. Check class, room and
   invigilator timetable conflicts transactionally and with PostgreSQL exclusions.
5. Restrict marks sheets to year/section/subject teacher assignments. Save drafts,
   validate and submit complete statuses, review independently, return with reasons,
   approve through the configured principal gate and explicitly publish.
6. Keep published report data, school identity, policy, marks, remarks and permitted
   image bytes in append-only publication snapshots. Independent corrections create
   new publication versions; previous issued report cards remain reproducible.
7. Expose only published permitted results to students and linked guardians. Hide
   withheld marks throughout HTML, charts, exports, PDFs and notifications. Scope
   exam controllers to explicit session assignments and teacher analytics to subjects.
8. Provide real-data dashboards, date sheets, entry/review/publication screens,
   accessible forms, confirmation dialogs, branded A4 report cards, filters and charts.
   Rankings are opt-in; promotion recommendations never change enrollments.
9. Extend only the gated fictional seed without overwriting existing records. Add
   permission, calculation, transition, history, database and concurrency tests;
   exercise complete workflows in an isolated browser test database.
10. Apply safe migrations, run all regression/security checks, compare preservation
    fingerprints, update documentation, commit, synchronize main without force and
    verify GitHub Actions. Do not deploy or start fees/finance or another phase.
