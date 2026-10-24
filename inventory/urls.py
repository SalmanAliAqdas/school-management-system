from django.urls import path

from . import views

app_name = "inventory"
urlpatterns = [
    path("", views.overview, name="overview"),
    path("movements/new/", views.movement, name="movement"),
]
