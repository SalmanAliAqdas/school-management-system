from django.urls import path

from . import views

app_name = "library"
urlpatterns = [
    path("", views.overview, name="overview"),
    path("issue/", views.issue_view, name="issue"),
    path("loans/<int:pk>/return/", views.return_view, name="return"),
]
