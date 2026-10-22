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

# Administrative capabilities are explicit; dashboard access alone never grants writes.
OPERATIONS = [
    "people.add_student",
    "people.change_student",
    "people.import_students",
    "people.transition_students",
    *[
        f"people.{verb}_{model}"
        for model in ("guardian", "teacher", "staff", "guardianstudent")
        for verb in ("view", "add", "change")
    ],
    "people.delete_guardianstudent",
    *[
        f"academics.{verb}_{model}"
        for model in (
            "academicyear",
            "term",
            "schoolclass",
            "section",
            "subject",
            "classsubject",
            "teachingassignment",
        )
        for verb in ("view", "add", "change")
    ],
]
for role in ("System Administrator", "School Administrator", "Principal"):
    ROLE_PERMISSIONS[role] += OPERATIONS
ROLE_PERMISSIONS["HR Manager"] += [
    f"people.{verb}_{model}" for model in ("teacher", "staff") for verb in ("view", "add", "change")
]


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
