# Permission matrix

Multiple groups are supported. These are initial capabilities, not completed
operational modules. `sync_roles` deterministically updates the eleven managed
groups; use separate custom groups for additional grants. Model permissions exist
after migrations; role groups must be explicitly initialized.

| Role | Dashboard | Student scope | School settings | Audit trail |
| --- | --- | --- | --- | --- |
| System Administrator | Administration | All | Change | Read |
| Principal | Administration | All | — | — |
| School Administrator | Administration | All | Change | — |
| Accountant | Administration shell | None | — | — |
| Examination Controller | Administration shell | None | — | — |
| Teacher | Teacher | Assigned section **and** academic year | — | — |
| Student | Student | Own explicitly attached profile | — | — |
| Parent or Guardian | Guardian | Explicit GuardianStudent links only | — | — |
| HR Manager | Administration shell | None | — | — |
| Librarian | Administration shell | None | — | — |
| Transport Manager | Administration shell | None | — | — |

Student lists, detail URLs, history and charts use the same selectors. A view
requires `people.view_student`; global scope also requires `people.view_all_students`.
Dashboard access alone never grants student access. Teachers see enrollment rows
only for the section/year of a TeachingAssignment; assigning another subject in
the same class must not grant mark-edit privileges when examinations are added.

The dashboard router selects Administration → Teacher → Student → Guardian in that
order, and authorized users can switch dashboards. Their data scope remains the
union of their authorized roles. Accounts without any dashboard permission receive
a 403 with a clear access message. Inaccessible student UUIDs return 404.

The Django admin additionally requires active, staff **and superuser** status.
The System Administrator application group does not set these flags. Creating a
superuser is a separate trusted provisioning operation. Group management is not
exposed to ordinary role users. Audit records cannot be edited or deleted in admin.

Operational permission names for exams, finance, payroll and other pending modules
are intentionally not granted. Accountants have no mark permissions. Before adding
each module, define its read/write/approve/export capabilities, object scope,
foreign-key validation and denial tests. Planned module descriptions contain no
protected records and are readable by signed-in accounts.

## School operations capabilities

System Administrator, School Administrator and Principal have explicit academic
view/add/change capabilities and admission, student edit, transition, import,
guardian-link and profile-management capabilities. Principal retains its existing
read-only boundary for school settings. HR Manager can view/create/change teacher
and staff profiles only. Other roles keep their foundation scope and cannot write
student or academic records, even when they can read a student.

Every student write requires both its action capability and global student read
scope (`people.view_student` plus `people.view_all_students`). Write services repeat
the view's permission check; crafted foreign keys cannot grant restricted readers
write access. Imports additionally require `people.import_students`, admission
permission, batch ownership and an unused, unexpired preview. Permissions are
rechecked at confirmation. Scoped selectors also govern printable records and images.

Historical enrollment/admin records are read-only. Operational profile admin allows
trusted superusers to attach login accounts; ordinary profile/academic edits use
the guarded application services. No managed role receives student or enrollment
delete permission. Run `sync_roles` after migration to update existing groups.

## Phase 3 attendance permissions

| Role | Student attendance | Student marking | Staff attendance | Corrections / leave |
| --- | --- | --- | --- | --- |
| System Administrator | All | All sections | All; register management | Review others; historical override |
| School Administrator | All | All sections | All; register management | Review others; historical override |
| Principal | All | All sections | All; register management | Review others; historical override |
| Teacher | Assigned year/section | Assigned year/section | Own employee profile | Request assigned-student/own-staff corrections and own leave |
| Student | Own published rows | None | None | No marking or approval |
| Parent or Guardian | Linked children's published rows/notices | None | None | No marking or approval |
| HR Manager | None | None | All; register management | Staff correction/leave review; no self-approval |
| Other staff roles | None | None | Own linked employee profile | Own correction and leave requests |

Read, mark, request, approve, global oversight, policy management and historical-window
capabilities are separate. Teacher assignment is checked against the actual register's
year and section. Submitted roster IDs must exactly match valid dated enrollments or
employment dates. A forged action permission does not grant global student oversight.
Services repeat checks independently of form/URL validation. Finalized row changes
require a matching approved correction; draft and finalized data are separate scopes.

Students and guardians never see drafts, internal correction queues or unrelated
rows. Removing a guardian link immediately revokes notice/detail/export access.
Staff read scope is independent from student scope. CSV/PDF/print exports reapply
scope before filtering and aggregating; client-supplied employee/student IDs cannot
expand it. All mutation endpoints require POST/CSRF and appropriate capabilities.


## Phase 4 examination capabilities

Run `sync_roles` after applying examination migrations. Existing authentication,
people and attendance grants remain; examination grants are additive and explicit.

| Role | Setup / scope | Marks | Review / final approval | Publication / corrections |
| --- | --- | --- | --- | --- |
| System Administrator | Global examination oversight and configuration | All | Review and final approval | Publish, independent correction decisions and recommendation overrides |
| Principal | Global examination oversight and configuration | All | Review and final approval | Publish, independent correction decisions and recommendation overrides |
| School Administrator | Global examination oversight and configuration | All | Controller review; no principal approval grant | Publish approved results and independent correction decisions |
| Examination Controller | Explicitly controlled sessions; may create sessions and assign reviewers within their scope | No marks-entry grant | Scoped controller review; final approval only when policy disables principal gate | Scoped publication and independent correction/amendment decisions |
| Teacher | Assigned year + section + subject | Assigned subject sheets | Submit; no review/approval grant | Request corrections for assigned approved marks; subject-only analytics |
| Student | Own published/archived results and eligible schedules | None | None | Own reports, versions, images and authorized downloads |
| Parent or Guardian | Currently linked children, including multiple children | None | None | Linked-child reports, images, downloads and notices |
| Other staff roles | No examination grant | None | None | None |

Permissions are capability and object checks, not dashboard implications. All service
methods recheck scope, foreign keys and action grants. Controllers cannot use a source
session without examination oversight for it. Teacher assignments are correlated by
all three academic keys; unrelated subject sheets and overall report cards remain
inaccessible. Unlinking a guardian or removing role/assignment access takes effect on
all reads and exports immediately. Independent review defaults on and prevents own
submission approval; correction/amendment decisions always require another actor.

Students/guardians never receive draft previews, withheld marks, other students'
rankings, private correction reasons or staff review records. A currently withheld
report also blocks its older versions. Historical authorization is checked at request
time rather than copied from the snapshot. See [examination policy](EXAMINATION_POLICY.md).

## Phase 5 finance permissions

| Actor | Finance capability |
| --- | --- |
| System Administrator / Principal | Configure, enter, report, independently approve, senior review and controlled reopen |
| School Administrator | Manage fees, generate/issue approved invoices, request corrections/expenses; cannot approve finance decisions |
| Accountant | Billing, manual collections, allocation, expense entry, reconciliation, reporting and closing requests; cannot configure policies or approve decisions |
| Optional custom cashier group | `CASHIER_PERMISSIONS`: finance access/all-student account reads, manual collection and credit allocation; no approval, setup, journal or exports |
| Student / Parent or Guardian | Current policy and explicit relationship-scoped issued invoices, receipts and statements only |
| Other managed roles | No finance access unless separately granted |

The eleven managed groups remain unchanged. Run `manage.py sync_roles` after migrations.
An optional cashier group is not a twelfth managed role. Custom cashier-only users
land on their finance workspace after login. Public services recheck action grants;
selectors recheck student ownership and guardian links. Requesters cannot review
their own financial decisions. Download and private attachment checks apply to each
object; report and journal grants remain separate from collection permissions.
