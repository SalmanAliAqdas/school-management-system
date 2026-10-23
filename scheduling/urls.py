from django.urls import path

from . import views

app_name = "scheduling"
urlpatterns = [
    path("assignments/<int:pk>/access/", views.assignment_access, name="assignment_access"),
    path("reports/", views.reports, name="reports"),
    path("duties/<int:pk>/", views.duty, name="duty"),
    path("lessons/<int:pk>/remove/", views.remove, name="remove"),
    path("<int:pk>/suggest/", views.suggest, name="suggest"),
    path("", views.overview, name="overview"),
    path("new/", views.create, name="create"),
    path("setup/<str:kind>/", views.setup, name="setup"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/edit/", views.create, name="edit"),
    path("<int:pk>/lessons/new/", views.entry, name="entry"),
    path("<int:pk>/lessons/<int:entry_id>/", views.entry, name="entry_edit"),
    path("<int:pk>/action/<str:action>/", views.action, name="action"),
    path("lessons/<int:pk>/substitute/", views.substitute, name="substitute"),
]
