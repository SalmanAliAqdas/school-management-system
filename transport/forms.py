from django import forms

from core.form_mixins import StyledFormMixin

from .models import StudentAssignment


class AssignmentForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = StudentAssignment
        fields = [
            "student",
            "trip",
            "pickup_stop",
            "dropoff_stop",
            "starts_on",
            "ends_on",
            "guardian_contact_allowed",
            "fee_assignment",
        ]
        widgets = {
            "starts_on": forms.DateInput(attrs={"type": "date"}),
            "ends_on": forms.DateInput(attrs={"type": "date"}),
        }
