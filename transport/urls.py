from django.urls import path

from . import views

app_name = "transport"
urlpatterns = [
    path("", views.overview, name="overview"),
    path("assignments/new/", views.assignment, name="assignment"),
]
