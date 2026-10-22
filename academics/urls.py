from django.urls import path

from . import views

app_name = "academics"
urlpatterns = [
    path("", views.academic_list, name="overview"),
    path("<slug:kind>/", views.academic_list, name="list"),
    path("<slug:kind>/new/", views.academic_edit, name="create"),
    path("<slug:kind>/<int:pk>/edit/", views.academic_edit, name="edit"),
    path("<slug:kind>/<int:pk>/<slug:action>/", views.academic_action, name="action"),
]
