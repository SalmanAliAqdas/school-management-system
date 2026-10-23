from django.urls import path

from . import views

app_name = "communications"
urlpatterns = [
    path("", views.overview, name="overview"),
    path("calendar/", views.calendar, name="calendar"),
    path("publications/new/", views.edit, name="create"),
    path("publications/<int:pk>/", views.publication, name="publication"),
    path("publications/<int:pk>/edit/", views.edit, name="edit"),
    path(
        "publications/<int:pk>/action/<str:action>/",
        views.publication_action,
        name="publication_action",
    ),
    path("messages/", views.inbox, name="inbox"),
    path("messages/new/", views.compose, name="compose"),
    path("messages/<int:pk>/", views.thread, name="thread"),
    path("messages/<int:pk>/read/", views.read_thread, name="read"),
    path("report/<int:pk>/", views.report, name="report"),
    path("moderation/", views.moderation, name="moderation"),
    path("moderation/<int:pk>/", views.moderation, name="moderate"),
    path("documents/<int:pk>/", views.document, name="document"),
    path("policy/", views.policy, name="policy"),
]
