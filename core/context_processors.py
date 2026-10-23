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
    from portals.notifications import unread_count

    selected = request.session.get("selected_portal")
    match = request.resolver_match
    if match and match.kwargs.get("role"):
        selected = match.kwargs["role"]
    authorized = [
        key
        for key, _label, perm in DASHBOARDS
        if request.user.is_authenticated and request.user.has_perm(perm)
    ]
    if selected not in authorized:
        selected = next((key for key in authorized), None)
    return {
        "school_name": school.name if school else "RumiWare SchoolOS",
        "school": school,
        "demo_mode": settings.ALLOW_DEMO_DATA,
        "portal_role": selected if selected in ("student", "parent", "teacher") else None,
        "unread_notifications": unread_count(request.user) if request.user.is_authenticated else 0,
        "display_density": request.session.get("display_density", "comfortable"),
        "available_dashboards": [
            {"key": key, "label": label}
            for key, label, permission in DASHBOARDS
            if request.user.is_authenticated and request.user.has_perm(permission)
        ],
    }
