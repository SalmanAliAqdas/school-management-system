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
