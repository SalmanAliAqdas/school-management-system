from django.urls import path

from . import views

app_name = "certificates"
urlpatterns = [
    path("", views.overview, name="overview"),
    path("requests/new/", views.request_document, name="request"),
    path("documents/<uuid:pk>/", views.download, name="download"),
    path("verify/<str:token>/", views.verify, name="verify"),
]
