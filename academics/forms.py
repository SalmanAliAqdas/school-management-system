from django import forms

from core.form_mixins import StyledFormMixin

from .models import (
    AcademicYear,
    ClassSubject,
    SchoolClass,
    Section,
    Subject,
    TeachingAssignment,
    Term,
)


def academic_form(model, fields):
    meta = type("Meta", (), {"model": model, "fields": fields})
    return type(f"{model.__name__}Form", (StyledFormMixin, forms.ModelForm), {"Meta": meta})


ACADEMIC_FORMS = {
    "years": academic_form(AcademicYear, ["name", "starts_on", "ends_on"]),
    "terms": academic_form(Term, ["academic_year", "name", "starts_on", "ends_on"]),
    "classes": academic_form(SchoolClass, ["name", "sort_order"]),
    "sections": academic_form(Section, ["school_class", "name"]),
    "subjects": academic_form(Subject, ["code", "name"]),
    "class-subjects": academic_form(ClassSubject, ["academic_year", "school_class", "subject"]),
    "assignments": academic_form(
        TeachingAssignment, ["teacher", "academic_year", "section", "subject"]
    ),
}


class PeriodActionForm(StyledFormMixin, forms.Form):
    confirm = forms.BooleanField(label="I confirm this academic period change.")
