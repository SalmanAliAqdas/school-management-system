from django import forms

from core.form_mixins import StyledFormMixin

from .models import Copy, Membership


class IssueForm(StyledFormMixin, forms.Form):
    copy = forms.ModelChoiceField(queryset=Copy.objects.filter(status="available"))
    membership = forms.ModelChoiceField(queryset=Membership.objects.filter(is_active=True))
