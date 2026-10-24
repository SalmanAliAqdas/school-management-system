from django import forms

from core.form_mixins import StyledFormMixin

from .models import StockMovement


class MovementForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = StockMovement
        fields = [
            "reference",
            "item",
            "kind",
            "quantity",
            "from_location",
            "to_location",
            "occurred_on",
            "reason",
            "expense",
        ]
        widgets = {"occurred_on": forms.DateInput(attrs={"type": "date"})}
