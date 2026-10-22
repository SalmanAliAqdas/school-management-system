from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "RumiWare SchoolOS · System administration"
admin.site.site_title = "SchoolOS"
admin.site.index_title = "Foundation configuration"
# Staff role users cannot bypass object policy through Django admin.
admin.site.has_permission = lambda request: (
    request.user.is_active and request.user.is_staff and request.user.is_superuser
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("students/", include("people.urls")),
    path("", include("core.urls")),
]
