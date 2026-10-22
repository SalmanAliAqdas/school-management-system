from django.urls import path

from . import views

app_name = "core"
urlpatterns = [
    path("", views.dashboard_redirect, name="dashboard"),
    path("health/", views.health, name="health"),
    path("dashboard/<str:role>/", views.role_dashboard, name="role_dashboard"),
    path("modules/", views.roadmap, name="roadmap"),
    path("modules/<slug:slug>/", views.module_detail, name="module_detail"),
    path("settings/school/", views.school_settings, name="school_settings"),
    path("branding/logo/", views.school_logo, name="school_logo"),
    path("profile/", views.profile, name="profile"),
    path("audit/", views.audit_log, name="audit"),
]
