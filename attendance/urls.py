from django.urls import path

from . import views

app_name = "attendance"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("staff/", views.dashboard, {"staff": True}, name="staff_dashboard"),
    path("register/", views.register, name="register"),
    path("staff/register/", views.register, {"staff": True}, name="staff_register"),
    path("students/<uuid:pk>/", views.student_detail, name="student"),
    path("employees/<str:kind>/<int:pk>/", views.staff_detail, name="employee"),
    path("reports/<slug:kind>/", views.reports, name="reports"),
    path("settings/", views.settings_view, name="settings"),
    path("settings/policy/new/", views.policy_edit, name="policy_create"),
    path("settings/policy/<int:pk>/", views.policy_edit, name="policy_edit"),
    path("settings/calendar/new/", views.calendar_create, name="calendar_create"),
    path("settings/calendar/<int:pk>/cancel/", views.calendar_cancel, name="calendar_cancel"),
    path("corrections/", views.correction_list, name="corrections"),
    path(
        "corrections/<str:kind>/<int:pk>/request/",
        views.correction_create,
        name="correction_create",
    ),
    path("corrections/<int:pk>/review/", views.correction_decide, name="correction_decide"),
    path("leave/", views.leave_list, name="leaves"),
    path("leave/new/", views.leave_create, name="leave_create"),
    path("leave/<int:pk>/review/", views.leave_decide, name="leave_decide"),
    path("notifications/", views.notifications, name="notifications"),
    path("notifications/<int:pk>/read/", views.notification_read, name="notification_read"),
]
