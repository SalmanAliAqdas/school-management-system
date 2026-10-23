from django.urls import path

from . import views

app_name = "portals"
urlpatterns = [
    path("notifications/", views.notification_inbox, name="notifications"),
    path(
        "notifications/<slug:category>/<int:pk>/read/",
        views.notification_read,
        name="notification_read",
    ),
    path("switch/", views.switch, name="switch"),
    path("parent/select-child/", views.select_child, name="select_child"),
    path("settings/", views.settings, name="settings"),
    path("settings/password/", views.password_change, name="password_change"),
    path("teacher/classes/", views.classes, name="classes"),
    path("teacher/classes/<int:pk>/", views.classroom, name="classroom"),
    path(
        "teacher/classes/<int:pk>/students/<uuid:student_id>/",
        views.classroom,
        name="teacher_student",
    ),
    path("<slug:role>/", views.overview, name="overview"),
    path(
        "<slug:role>/students/<uuid:child_id>/<slug:section>/", views.student_page, name="student"
    ),
]
