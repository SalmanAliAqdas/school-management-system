from django.urls import path

from . import operations_views as operations
from . import views

app_name = "people"
urlpatterns = [
    path("", views.student_list, name="student_list"),
    path("admit/", operations.admission, name="admission"),
    path("import/", operations.import_upload, name="import"),
    path("import/template/", operations.import_template, name="import_template"),
    path("import/<uuid:pk>/confirm/", operations.import_confirm, name="import_confirm"),
    path("print/class/", operations.print_class, name="print_class"),
    path("directory/<slug:kind>/", operations.directory_list, name="directory"),
    path("directory/<slug:kind>/new/", operations.directory_edit, name="directory_create"),
    path("directory/<slug:kind>/<int:pk>/", operations.directory_detail, name="directory_detail"),
    path("directory/<slug:kind>/<int:pk>/edit/", operations.directory_edit, name="directory_edit"),
    path("guardian-links/new/", operations.guardian_link, name="guardian_link"),
    path("guardian-links/<int:pk>/edit/", operations.guardian_link, name="guardian_link_edit"),
    path("guardian-links/<int:pk>/remove/", operations.guardian_unlink, name="guardian_unlink"),
    path("images/<slug:kind>/<str:pk>/", operations.profile_image, name="image"),
    path("<uuid:pk>/", views.student_detail, name="student_detail"),
    path("<uuid:pk>/edit/", operations.student_edit, name="student_edit"),
    path("<uuid:pk>/roll/", operations.student_roll, name="student_roll"),
    path("<uuid:pk>/enrollment/", operations.student_transition, name="student_transition"),
    path("<uuid:pk>/print/<slug:kind>/", operations.print_student, name="print_student"),
]
