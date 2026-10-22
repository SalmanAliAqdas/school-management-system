from django.contrib import admin

from people.admin import HistoricalAdmin

from .models import (
    AcademicYear,
    ClassSubject,
    SchoolClass,
    Section,
    Subject,
    TeachingAssignment,
    Term,
)

for model in (AcademicYear, SchoolClass, Section, Subject, TeachingAssignment, Term, ClassSubject):
    admin.site.register(model, HistoricalAdmin)
