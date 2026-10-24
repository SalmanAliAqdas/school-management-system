from django.urls import path

from . import views

app_name = "analytics"
urlpatterns = [
    path("", views.executive, name="executive"),
    path("reports/", views.center, name="center"),
    path("reports/<slug:category>/", views.report, name="report"),
    path("quality/", views.quality, name="quality"),
    path("students/<uuid:pk>/", views.student_progress, name="student_progress"),
]
