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

ATTENDANCE_ADMIN = [
    "attendance.view_attendance",
    "attendance.mark_attendance",
    "attendance.view_all_attendance",
    "attendance.manage_policy",
    "attendance.request_correction",
    "attendance.approve_correction",
    "attendance.override_correction_window",
    "attendance.view_staff_attendance",
    "attendance.view_all_staff_attendance",
    "attendance.manage_staff_attendance",
    "attendance.request_staff_correction",
    "attendance.approve_staff_correction",
    "attendance.request_leave",
    "attendance.approve_leave",
]
for role in ("System Administrator", "School Administrator", "Principal"):
    ROLE_PERMISSIONS[role] += ATTENDANCE_ADMIN
ROLE_PERMISSIONS["Teacher"] += [
    "attendance.view_attendance",
    "attendance.mark_attendance",
    "attendance.request_correction",
]
for role in ("Student", "Parent or Guardian"):
    ROLE_PERMISSIONS[role] += ["attendance.view_attendance"]
for role in (
    "Teacher",
    "Accountant",
    "Examination Controller",
    "HR Manager",
    "Librarian",
    "Transport Manager",
):
    ROLE_PERMISSIONS[role] += [
        "attendance.view_staff_attendance",
        "attendance.request_staff_correction",
        "attendance.request_leave",
    ]
ROLE_PERMISSIONS["HR Manager"] += [
    "attendance.view_all_staff_attendance",
    "attendance.manage_staff_attendance",
    "attendance.approve_staff_correction",
    "attendance.approve_leave",
]


EXAM_OVERSIGHT = [
    "examinations.view_examinations",
    "examinations.view_all_examinations",
    "examinations.manage_examinations",
    "examinations.enter_marks",
    "examinations.review_results",
    "examinations.correct_results",
    "examinations.decide_corrections",
    "examinations.publish_results",
]
for role in ("System Administrator", "School Administrator", "Principal"):
    ROLE_PERMISSIONS[role] += EXAM_OVERSIGHT
for role in ("System Administrator", "Principal"):
    ROLE_PERMISSIONS[role] += ["examinations.approve_results", "examinations.override_promotion"]
ROLE_PERMISSIONS["Examination Controller"] += [
    "examinations.view_examinations",
    "examinations.manage_examinations",
    "examinations.review_results",
    "examinations.correct_results",
    "examinations.decide_corrections",
    "examinations.publish_results",
]
ROLE_PERMISSIONS["Teacher"] += [
    "examinations.view_examinations",
    "examinations.enter_marks",
    "examinations.correct_results",
]
for role in ("Student", "Parent or Guardian"):
    ROLE_PERMISSIONS[role] += ["examinations.view_examinations"]


FINANCE_READ = ["finance.access_finance", "finance.view_all_finance"]
CASHIER_PERMISSIONS = [*FINANCE_READ, "finance.collect_payments", "finance.allocate_credit"]
FINANCE_ENTRY = [
    *CASHIER_PERMISSIONS,
    "finance.generate_invoices",
    "finance.request_adjustments",
    "finance.record_expenses",
    "finance.reconcile_accounts",
    "finance.view_finance_reports",
    "finance.view_journal",
    "finance.close_financial_periods",
]
ROLE_PERMISSIONS["Accountant"] += FINANCE_ENTRY
ROLE_PERMISSIONS["School Administrator"] += [
    *FINANCE_READ,
    "finance.manage_fees",
    "finance.generate_invoices",
    "finance.request_adjustments",
    "finance.record_expenses",
]
for role in ("System Administrator", "Principal"):
    ROLE_PERMISSIONS[role] += [
        *FINANCE_ENTRY,
        "finance.manage_finance",
        "finance.manage_fees",
        "finance.approve_finance",
        "finance.approve_senior_finance",
        "finance.reopen_financial_periods",
    ]
for role in ("Student", "Parent or Guardian"):
    ROLE_PERMISSIONS[role] += ["finance.access_finance"]


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
