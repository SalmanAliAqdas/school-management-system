from django.contrib.auth.models import Group, Permission
from django.db import transaction

ADMIN_DASHBOARD = "accounts.access_admin_dashboard"
STUDENT_READ = "people.view_student"
GLOBAL_STUDENTS = "people.view_all_students"

ROLE_PERMISSIONS = {
    "System Administrator": [
        ADMIN_DASHBOARD,
        STUDENT_READ,
        GLOBAL_STUDENTS,
        "core.change_schoolsettings",
        "audit.view_auditevent",
    ],
    "Principal": [ADMIN_DASHBOARD, STUDENT_READ, GLOBAL_STUDENTS],
    "School Administrator": [
        ADMIN_DASHBOARD,
        STUDENT_READ,
        GLOBAL_STUDENTS,
        "core.change_schoolsettings",
    ],
    "Accountant": [ADMIN_DASHBOARD],
    "Examination Controller": [ADMIN_DASHBOARD],
    "Teacher": ["accounts.access_teacher_dashboard", STUDENT_READ],
    "Student": ["accounts.access_student_dashboard", STUDENT_READ],
    "Parent or Guardian": ["accounts.access_parent_dashboard", STUDENT_READ],
    "HR Manager": [ADMIN_DASHBOARD],
    "Librarian": [ADMIN_DASHBOARD],
    "Transport Manager": [ADMIN_DASHBOARD],
}


@transaction.atomic
def sync_roles():
    """Synchronize only managed groups; fail if migrations are missing."""
    for role, permissions in ROLE_PERMISSIONS.items():
        group, _ = Group.objects.get_or_create(name=role)
        resolved = []
        for permission in permissions:
            app_label, codename = permission.split(".", 1)
            resolved.append(
                Permission.objects.get(content_type__app_label=app_label, codename=codename)
            )
        group.permissions.set(resolved)
