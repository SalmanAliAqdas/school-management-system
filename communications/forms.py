from django import forms

from learning.forms import MultipleFiles

from .models import CommunicationPolicy, Publication


class PublicationForm(forms.ModelForm):
    files = MultipleFiles()
    expected = forms.IntegerField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = Publication
        fields = [
            "kind",
            "title",
            "body",
            "category",
            "audience",
            "academic_year",
            "section",
            "publish_at",
            "expires_at",
            "starts_at",
            "ends_at",
            "location",
            "pinned",
            "important",
        ]
        widgets = {
            name: forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")
            for name in ["publish_at", "expires_at", "starts_at", "ends_at"]
        }


class MessageForm(forms.Form):
    body = forms.CharField(max_length=10000, widget=forms.Textarea, label="Message")
    files = MultipleFiles()


class ConversationForm(MessageForm):
    from django.contrib.auth import get_user_model

    from people.models import Student

    subject = forms.CharField(max_length=160)
    student = forms.ModelChoiceField(
        queryset=Student.objects.none(), required=False, label="Child (for family conversations)"
    )
    recipient = forms.ModelChoiceField(queryset=get_user_model().objects.none())


class ReportForm(forms.Form):
    reason = forms.CharField(max_length=1000, widget=forms.Textarea)


class ModerationForm(forms.Form):
    resolution = forms.CharField(max_length=1000, widget=forms.Textarea)
    hide = forms.BooleanField(required=False, label="Hide message from participants")
    block = forms.BooleanField(required=False, label="Block further replies")


PolicyForm = forms.modelform_factory(
    CommunicationPolicy, fields=["messages_per_hour", "retention_days", "require_approval"]
)
