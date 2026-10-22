from django.urls import path

from . import views

app_name = "examinations"
urlpatterns = [
    path(
        "amendments/candidates/<uuid:candidate_id>/",
        views.amendment_request,
        name="amendment_request",
    ),
    path(
        "amendments/<uuid:amendment_id>/review/",
        views.amendment_decision,
        name="amendment_decision",
    ),
    path("", views.dashboard, name="dashboard"),
    path("setup/<slug:kind>/", views.setup, name="setup"),
    path("setup/<slug:kind>/new/", views.setup_edit, name="setup_new"),
    path("setup/<slug:kind>/<str:pk>/edit/", views.setup_edit, name="setup_edit"),
    path("setup/<slug:kind>/<str:pk>/remove/", views.setup_remove, name="setup_remove"),
    path("sessions/<uuid:session_id>/", views.session_detail, name="session"),
    path("sessions/<uuid:session_id>/actions/<slug:action>/", views.transition, name="transition"),
    path("sessions/<uuid:session_id>/schedule/", views.schedule_edit, name="schedule_edit"),
    path("sessions/<uuid:session_id>/analytics/", views.analysis, name="analytics"),
    path("schedules/", views.schedules, name="schedules"),
    path("marks/<int:sheet_id>/", views.marks_entry, name="marks"),
    path("marks/<int:sheet_id>/review/", views.sheet_review, name="sheet_review"),
    path("candidates/<uuid:candidate_id>/", views.candidate_detail, name="candidate"),
    path(
        "candidates/<uuid:candidate_id>/recommendation/",
        views.recommendation,
        name="recommendation",
    ),
    path("results/", views.results, name="results"),
    path("reports/<uuid:result_id>/", views.report, name="report"),
    path("reports/<uuid:result_id>/images/<slug:kind>/", views.report_image, name="report_image"),
    path("corrections/", views.corrections, name="corrections"),
    path("corrections/marks/<int:entry_id>/", views.correction_request, name="correction_request"),
    path(
        "corrections/<uuid:correction_id>/review/",
        views.correction_decision,
        name="correction_decision",
    ),
    path("notifications/", views.notifications, name="notifications"),
    path("notifications/<int:pk>/read/", views.notification_read, name="notification_read"),
]
