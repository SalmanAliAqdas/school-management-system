from django import forms

from .models import Assignment


class MultipleInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFiles(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleInput())
        kwargs.setdefault("required", False)
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        values = data if isinstance(data, (list, tuple)) else [data] if data else []
        return [super(MultipleFiles, self).clean(item, initial) for item in values]


class AssignmentForm(forms.ModelForm):
    files = MultipleFiles()
    expected = forms.IntegerField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = Assignment
        fields = [
            "teaching",
            "title",
            "description",
            "kind",
            "publish_at",
            "due_at",
            "maximum",
            "rubric",
            "late_allowed",
            "late_penalty",
            "submission_required",
        ]
        widgets = {
            name: forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")
            for name in ["publish_at", "due_at"]
        }


class SubmissionForm(forms.Form):
    text = forms.CharField(required=False, max_length=20000, widget=forms.Textarea)
    files = MultipleFiles()
    expected = forms.IntegerField(initial=0, widget=forms.HiddenInput)
    final = forms.BooleanField(
        required=False, label="Submit final work (leave unchecked to save draft)"
    )


class FeedbackForm(forms.Form):
    text = forms.CharField(max_length=10000, widget=forms.Textarea, label="Feedback")
    outcome = forms.ChoiceField(
        choices=[(x, x.title()) for x in ["reviewed", "graded", "returned", "excused"]]
    )
    marks = forms.DecimalField(required=False, min_value=0, max_digits=7, decimal_places=2)
    criterion_marks = forms.JSONField(required=False, initial=dict)
    released = forms.BooleanField(required=False, label="Release to student")
    guardian_visible = forms.BooleanField(
        required=False, label="Also allow linked guardians to view feedback"
    )
