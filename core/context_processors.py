from django.conf import settings

from .models import SchoolSettings

DASHBOARDS = [
    ("admin", "Administration", "accounts.access_admin_dashboard"),
    ("teacher", "Teaching", "accounts.access_teacher_dashboard"),
    ("student", "Student", "accounts.access_student_dashboard"),
    ("parent", "Guardian", "accounts.access_parent_dashboard"),
]


def school_context(request):
    # Public error and authentication pages do not depend on the school table.
    school = SchoolSettings.objects.first() if request.user.is_authenticated else None
    return {
        "school_name": school.name if school else "RumiWare SchoolOS",
        "demo_mode": settings.ALLOW_DEMO_DATA,
        "available_dashboards": [
            {"key": key, "label": label}
            for key, label, permission in DASHBOARDS
            if request.user.is_authenticated and request.user.has_perm(permission)
        ],
    }
