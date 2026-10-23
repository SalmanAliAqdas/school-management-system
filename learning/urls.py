from django.urls import path

from . import views

app_name = "learning"
urlpatterns = [
    path("reports/", views.reports, name="reports"),
    path("<int:pk>/excuse/<uuid:student_id>/", views.excuse, name="excuse"),
    path("", views.overview, name="overview"),
    path("new/", views.edit, name="create"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/edit/", views.edit, name="edit"),
    path("<int:pk>/action/<str:action>/", views.action, name="action"),
    path("<int:pk>/submit/", views.submit, name="submit"),
    path("<int:pk>/export/", views.export, name="export"),
    path("submissions/<int:pk>/review/", views.review, name="review"),
    path("attachments/<int:pk>/", views.attachment, name="attachment"),
]
