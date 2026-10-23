from django import forms
from django.contrib.auth.forms import PasswordChangeForm

from core.form_mixins import StyledFormMixin


class AccountPreferencesForm(StyledFormMixin, forms.Form):
    phone = forms.CharField(max_length=40, required=False, label="Contact phone")
    density = forms.ChoiceField(
        choices=[("comfortable", "Comfortable"), ("compact", "Compact")],
        label="Display spacing",
    )

    def __init__(self, *args, contact_profiles=(), **kwargs):
        super().__init__(*args, **kwargs)
        if not contact_profiles:
            del self.fields["phone"]


class SecurePasswordChangeForm(StyledFormMixin, PasswordChangeForm):
    pass
