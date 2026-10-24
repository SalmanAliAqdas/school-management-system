from django import forms

from core.form_mixins import StyledFormMixin

from .models import Employee, EmploymentRecord


class EmployeeForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Employee
        fields = ["user", "staff", "teacher", "employee_code", "emergency_contact", "status"]


class EmploymentForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = EmploymentRecord
        fields = [
            "department",
            "designation",
            "manager",
            "employment_type",
            "starts_on",
            "probation_ends_on",
            "reason",
        ]
        widgets = {
            "starts_on": forms.DateInput(attrs={"type": "date"}),
            "probation_ends_on": forms.DateInput(attrs={"type": "date"}),
        }
