from django import forms

from .form_mixins import ImageFormMixin
from .models import SchoolSettings


class SchoolSettingsForm(ImageFormMixin, forms.ModelForm):
    class Meta:
        model = SchoolSettings
        fields = [
            "name",
            "logo",
            "address",
            "phone",
            "email",
            "website",
            "principal_name",
            "principal_email",
            "principal_phone",
            "timezone",
            "currency",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"
