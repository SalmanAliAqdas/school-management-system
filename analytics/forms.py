from django import forms

from academics.models import AcademicYear
from core.form_mixins import StyledFormMixin


class AnalyticsFilterForm(StyledFormMixin, forms.Form):
    academic_year = forms.ModelChoiceField(queryset=AcademicYear.objects.all(), required=False)
    starts_on = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    ends_on = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))

    def clean(self):
        data = super().clean()
        year = data.get("academic_year") or AcademicYear.objects.filter(is_current=True).first()
        if not year:
            year = AcademicYear.objects.order_by("-starts_on").first()
        start = data.get("starts_on") or (year.starts_on if year else None)
        end = data.get("ends_on") or (year.ends_on if year else None)
        if start and end and (end < start or (end - start).days > 731):
            raise forms.ValidationError("Choose an ordered date range of at most two years.")
        if year and start and end:
            start, end = max(start, year.starts_on), min(end, year.ends_on)
        data.update(academic_year=year, starts_on=start, ends_on=end)
        return data
