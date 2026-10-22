from django.urls import path

from . import views

app_name = "people"
urlpatterns = [
    path("", views.student_list, name="student_list"),
    path("<uuid:pk>/", views.student_detail, name="student_detail"),
]
