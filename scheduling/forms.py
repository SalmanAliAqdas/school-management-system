from django import forms

from .models import Availability, Entry, Period, Room, Timetable, WorkloadLimit


def form_for(model, fields):
    return forms.modelform_factory(
        model,
        fields=fields,
        widgets={
            "starts_on": forms.DateInput(attrs={"type": "date"}),
            "ends_on": forms.DateInput(attrs={"type": "date"}),
            "starts_at": forms.TimeInput(attrs={"type": "time"}),
            "ends_at": forms.TimeInput(attrs={"type": "time"}),
        },
    )


SETUP = {
    "rooms": form_for(Room, ["name", "kind", "is_active"]),
    "periods": form_for(
        Period, ["academic_year", "shift", "name", "weekday", "starts_at", "ends_at", "kind"]
    ),
    "availability": form_for(Availability, ["teacher", "period", "kind"]),
    "limits": form_for(WorkloadLimit, ["teacher", "daily", "weekly"]),
}
TimetableForm = form_for(Timetable, ["title", "academic_year", "term", "starts_on", "ends_on"])
EntryForm = form_for(Entry, ["period", "assignment", "room"])


class SubstitutionForm(forms.Form):
    from people.models import Teacher

    date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    teacher = forms.ModelChoiceField(queryset=Teacher.objects.filter(is_active=True))
    reason = forms.CharField(max_length=500, widget=forms.Textarea)
    approve = forms.BooleanField(required=False, label="Approve substitution")
