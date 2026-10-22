from django.contrib import admin

from .models import Enrollment, Guardian, GuardianStudent, Staff, Student, Teacher


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ["admission_number", "first_name", "last_name", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["admission_number", "first_name", "last_name"]

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields if field.name != "user"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


for model in (Guardian, Staff, Teacher):
    profile_admin = type(
        f"{model.__name__}Admin",
        (StudentAdmin,),
        {
            "list_display": ["first_name", "last_name"],
            "list_filter": [],
            "search_fields": ["first_name", "last_name"],
        },
    )
    admin.site.register(model, profile_admin)


class HistoricalAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


for model in (Enrollment, GuardianStudent):
    admin.site.register(model, HistoricalAdmin)
