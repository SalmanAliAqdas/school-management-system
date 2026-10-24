from django import forms

from core.form_mixins import StyledFormMixin

from .models import DocumentRequest


class RequestForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = DocumentRequest
        fields = ["document_type", "student", "employee", "purpose"]


class DecisionForm(StyledFormMixin, forms.Form):
    action = forms.ChoiceField(choices=[("approve", "Approve"), ("reject", "Reject")])
    reason = forms.CharField(max_length=500, required=False)
