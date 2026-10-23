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

    def clean_currency(self):
        currency = self.cleaned_data["currency"]
        from finance.models import FinanceSettings

        financial = FinanceSettings.objects.first()
        if financial and financial.currency != currency:
            raise forms.ValidationError(
                "Base currency is controlled by finance settings. Conversion is not supported."
            )
        return currency
