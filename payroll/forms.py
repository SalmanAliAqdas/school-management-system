from django import forms

from core.form_mixins import StyledFormMixin
from hr.models import Employee

from .models import PayrollPeriod


class GenerateForm(StyledFormMixin, forms.Form):
    period = forms.ModelChoiceField(queryset=PayrollPeriod.objects.filter(state="open"))
    employees = forms.ModelMultipleChoiceField(
        queryset=Employee.objects.filter(status__in=["active", "probation", "notice"])
    )
