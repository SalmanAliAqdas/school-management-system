# School administration and academic operations

This phase extends the existing single-school Django monolith. Admissions belong
to `people`; academic setup belongs to `academics`. Services own authorized writes,
selectors own restricted reads, and templates provide the administration interface.

## Setup and daily use

1. Apply migrations and run `python manage.py sync_roles`. Existing managed groups
   receive the new permissions without changing account passwords or staff flags.
2. In **School settings**, enter the school name, address, contact and principal
   information and optionally upload a logo. The logo appears in the workspace
   and printable records. Application timestamps still use the environment timezone.
3. In **Academics**, create years, classes, sections and subjects. Assign subjects
   to a class/year before assigning teachers to a section/year/subject. Define
   term dates within the parent year and activate the desired year and term.
4. Create guardian, teacher and staff profiles from the management navigation.
   Profiles can exist without login accounts. Trusted system administrators can
   attach existing accounts through the profile's `user` field in Django admin.
   Account creation and privilege assignment retain the foundation's controls.
5. Use **Students > Admit student**. Enter birth/admission/start dates, placement
   and optional roll number, image and existing guardian. Admission numbers use
   the automatic, school-wide `RW-0000001` sequence. Existing legacy numbers remain.
6. Use **Link a guardian** for additional relationships. One guardian can have
   several children and one child can have several guardians. Link changes and
   removal affect guardian portal scope immediately; removal requires confirmation.
7. Use the student's **Change enrollment** page to transfer section, promote,
   withdraw, graduate or transfer to another school. Review the destination, dates
   and confirmation checkbox. Previous placement rows remain visible in history.

Directory pages provide search, sorting, filtering and 20-row pagination. Student
filters include year, class and section; all reads and prints retain the original
student/guardian/teacher object scope. Student profiles, admission records and class
lists have print layouts; use the browser's Print command to print or save as PDF.
Class lists can include all placements or only active placements via `status=all`
or `status=active`; a historical list can contain successive placements of a child.

## Academic lifecycle and history

- A year or term starts **open**, with a separate current-period flag. Activation
  switches the current year, or current term within the selected year.
- Closing a year requires all its active enrollments to have been resolved.
  It closes its open terms too. Archive only follows closure and archives terms.
  Closed/archived years cannot receive new admissions or placements or reopen.
- A section transfer closes the current placement on the selected date and starts
  the new one the following day in the same year. Select a different section.
- Promotion closes the current placement and creates a placement in a later,
  non-overlapping year at a higher class sort order, starting on the year's first
  day. These are immediate recorded changes, not scheduled jobs.
- Withdrawal, graduation and transfer out close the placement and retain an inactive
  student profile with the corresponding status. There is no destructive student
  delete or history editing workflow. Readmission and exceptional corrections are
  outside this phase and require a separately designed, audited workflow.
- Admission number/date/source reference cannot be edited after admission. Student
  contact identity corrections are permitted while active. Completed enrollment
  rows cannot be updated/deleted, including direct ORM writes; active placement
  identity is immutable. **Correct roll number** allows an audited correction to
  an active placement, with uniqueness and stale-form checks. Historical roll
  numbers remain protected. Year/class/section/subject definitions already in use are
  protected through services and read-only admin configuration. Teaching assignments
  can be corrected while their year is open; closed-year assignments are protected.
- Existing admission dates are backfilled from the earliest placement, falling back
  to profile creation date when no placement exists. Missing legacy birth dates
  remain unknown. Existing teaching assignments generate matching class subjects.

## CSV preview and confirmation

Download the template from **Import CSV**. Files must be UTF-8 (an optional BOM is
accepted), at most 1 MB and 500 students. Headers are strict; dates use YYYY-MM-DD.

| Column | Meaning |
| --- | --- |
| external_reference | Required stable source ID, unique without regard to case |
| first_name, last_name | Required student names |
| admission_date, date_of_birth | Required dates; birth must precede admission |
| academic_year, section | Required numeric IDs from academic setup tables |
| started_on | Required placement date inside an open year and on/after admission |
| roll_number | Optional; unique among active students in the section/year |
| guardian, relationship | Optional existing guardian ID and required relationship when linked |

The preview displays row errors, invalid choices, duplicate source references,
matching names/birth dates and duplicate active roll numbers. Suspected duplicates
are blocked for review of the existing student. Fix errors and upload again;
there is no silent skipping or partial import. New guardian creation is a separate
workflow so imports cannot accidentally create duplicate family contacts.

A valid preview stores rows privately in PostgreSQL for 30 minutes. Only its uploader
can confirm it and must still have admission/import/global access. Confirmation
revalidates against current records, locks years in a consistent order, and writes
all students in one transaction. Any failure rolls everything back. Confirmation
is single-use and clears the staged personal rows. Schedule this command to clear
expired preview rows while retaining batch identifiers:

```powershell
python manage.py purge_admission_previews
```

## Permissions and storage

System Administrator, School Administrator and Principal receive operational
capabilities. HR Manager can manage staff/teacher profiles; other foundation roles
retain their scoped read capabilities. Student writes require the particular action
permission plus `people.view_student` and `people.view_all_students`. Dashboard
access alone grants no writes. CSV ownership and object scope are checked server-side.

Student/teacher photos and school logos accept decoded PNG/JPEG up to 2 MB and
16 million input pixels. Images are re-encoded as PNG, resized within 1200×1200,
and stripped of metadata, with random storage names. Uploaded files are outside
static assets. Authenticated image routes check record scope and send private,
no-store responses. There is no public media route. Replaced files are removed
after successful commit; failed admission writes clean up their new image files.

Configure durable private storage before deployment. Filesystem/storage writes
cannot participate in a database transaction; process interruption can leave
unreferenced private files and requires operational reconciliation. Original images
are discarded. Other document types and malware scanning are not implemented here.

PostgreSQL migrations install trusted `btree_gist` for a placement-range exclusion
constraint. The migration account must be able to create that extension, or a
database administrator must install it first. Existing conflicting admissions or
overlapping placements must be reviewed before upgrading; migrations do not delete
or silently merge historical records. The normal application database user should
not have schema/trigger management privileges.
