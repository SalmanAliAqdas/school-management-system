from django.contrib import admin

from .models import AcademicYear, SchoolClass, Section, Subject, TeachingAssignment, Term

for model in (AcademicYear, SchoolClass, Section, Subject, TeachingAssignment, Term):
    admin.site.register(model)
