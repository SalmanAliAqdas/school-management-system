# Database design

## Foundation relationships

```mermaid
erDiagram
    User ||--o| Student : account
    User ||--o| Guardian : account
    User ||--o| Teacher : account
    User ||--o| Staff : account
    Guardian ||--o{ GuardianStudent : links
    Student ||--o{ GuardianStudent : children
    Student ||--o{ Enrollment : history
    AcademicYear ||--o{ Term : contains
    AcademicYear ||--o{ Enrollment : scopes
    SchoolClass ||--o{ Section : contains
    Section ||--o{ Enrollment : receives
    Teacher ||--o{ TeachingAssignment : teaches
    Subject ||--o{ TeachingAssignment : subject
    Section ||--o{ TeachingAssignment : section
    AcademicYear ||--o{ TeachingAssignment : year
    User ||--o{ AuditEvent : actor
```

User accounts are independent from people profiles; a profile may exist before
an account is provisioned. Deleting an account detaches profiles, retaining school
records. Enrollment, guardian links, assignments and academic references use
PROTECT. Audit actors use SET_NULL and retain a non-sensitive target identifier.

SchoolSettings is a singleton for one school, with an explicit timezone and
currency boundary. It is not a multi-tenant architecture. Future multi-school
support requires school foreign keys, scoped uniqueness and tenant access tests.

Academic years and terms have ordered date checks. Only one academic year can be
current. Terms must fall within their year (model validation). A student may have
multiple dated section placements in one year; one active placement per student
and year is enforced by a conditional unique constraint. Historical placement rows
are retained when a student changes class; close the previous placement and create
a new row in a transaction. Date ranges must not overlap (model validation);
future enrollment write services must lock the student row to prevent concurrent
overlaps. A class is derived from its section, avoiding a redundant class key.

Guardian links are explicit and unique per guardian/student. Assignments are unique
per teacher, subject, section and year. Record visibility matches the enrollment
year and section of teacher assignments. Subject-mark and attendance endpoints do
not exist yet and must enforce subject/date scope when implemented.

User email is required and case-insensitively unique at the database level.
Usernames remain Django's case-sensitive identifiers. Database indexes support
enrollment lookup by year/section/status and event lookup by type/date. UUID student
identifiers avoid sequential record URLs; authorization remains mandatory.

Future finance values use DecimalField, never floats. Marks use bounded
DecimalField values with database checks against assessment maximums. Neither
operational table is created in this foundation. All timestamps are timezone
aware; the default school timezone is Asia/Karachi.

Application validators run in ModelForm/admin and seed services; database checks
also protect critical single-row invariants. Direct ORM writes do not automatically
run full_clean. New write services must explicitly validate and use transactions.
