from django.urls import path

from . import views

app_name = "hr"
urlpatterns = [
    path("", views.overview, name="overview"),
    path("employees/new/", views.employee_new, name="employee_new"),
    path("employees/<int:pk>/employment/", views.employment, name="employment"),
    path("documents/<int:pk>/", views.document, name="document"),
]
