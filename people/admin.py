from django.contrib import admin

from .models import Enrollment, Guardian, GuardianStudent, Staff, Student, Teacher


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ["admission_number", "first_name", "last_name", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["admission_number", "first_name", "last_name"]


for model in (Enrollment, Guardian, GuardianStudent, Staff, Teacher):
    admin.site.register(model)
