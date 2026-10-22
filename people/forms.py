from django import forms
from django.utils import timezone

from academics.models import AcademicYear, Section
from core.form_mixins import ImageFormMixin, StyledFormMixin

from .models import Guardian, GuardianStudent, Staff, Student, Teacher


class StudentEditForm(ImageFormMixin, forms.ModelForm):
    class Meta:
        model = Student
        fields = ["first_name", "last_name", "date_of_birth", "photo"]


class AdmissionForm(StudentEditForm):
    date_of_birth = forms.DateField()
    academic_year = forms.ModelChoiceField(queryset=AcademicYear.objects.filter(status="open"))
    section = forms.ModelChoiceField(queryset=Section.objects.select_related("school_class"))
    started_on = forms.DateField(initial=timezone.localdate, label="Enrollment start date")
    roll_number = forms.CharField(max_length=24, required=False)
    guardian = forms.ModelChoiceField(
        queryset=Guardian.objects.order_by("first_name", "pk"), required=False
    )
    relationship = forms.CharField(max_length=48, required=False)

    class Meta(StudentEditForm.Meta):
        fields = [
            "first_name",
            "last_name",
            "admission_date",
            "date_of_birth",
            "external_reference",
            "photo",
        ]

    def clean(self):
        data = super().clean()
        if data.get("guardian") and not data.get("relationship"):
            self.add_error("relationship", "Describe this guardian's relationship to the child.")
        if data.get("admission_date") and data["admission_date"] > timezone.localdate():
            self.add_error("admission_date", "Admission date cannot be in the future.")
        year, start = data.get("academic_year"), data.get("started_on")
        if year and start and not year.starts_on <= start <= year.ends_on:
            self.add_error("started_on", "Choose a date inside the academic year.")
        if start and data.get("admission_date") and start < data["admission_date"]:
            self.add_error("started_on", "Enrollment cannot start before admission.")
        return data


class TransitionForm(StyledFormMixin, forms.Form):
    action = forms.ChoiceField(
        choices=[
            ("transfer", "Transfer to another section"),
            ("promote", "Promote to a new academic year"),
            ("withdraw", "Withdraw"),
            ("transfer_out", "Transfer to another school"),
            ("graduate", "Graduate"),
        ]
    )
    effective_on = forms.DateField(
        initial=timezone.localdate,
        help_text="Last day of the current placement. A section transfer starts the next day; "
        "promotion starts on the destination year's first day.",
    )
    expected_enrollment = forms.IntegerField(widget=forms.HiddenInput)
    academic_year = forms.ModelChoiceField(
        queryset=AcademicYear.objects.filter(status="open"), required=False
    )
    section = forms.ModelChoiceField(
        queryset=Section.objects.select_related("school_class"), required=False
    )
    roll_number = forms.CharField(max_length=24, required=False)
    notes = forms.CharField(
        max_length=500, widget=forms.Textarea(attrs={"rows": 3}), required=False
    )
    confirm = forms.BooleanField(
        label="I confirm this enrollment change and the dates shown above."
    )


class RollCorrectionForm(StyledFormMixin, forms.Form):
    expected_enrollment = forms.IntegerField(widget=forms.HiddenInput)
    roll_number = forms.CharField(max_length=24, required=False)
    confirm = forms.BooleanField(label="I confirm this correction to the active roll number.")


class GuardianForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Guardian
        fields = ["first_name", "last_name", "phone", "email", "address"]


class GuardianLinkForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = GuardianStudent
        fields = ["guardian", "student", "relationship"]


class EmploymentFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].required = False

    def clean_department(self):
        return (
            self.cleaned_data.get("department")
            or self._meta.model._meta.get_field("department").get_default()
        )


class TeacherForm(EmploymentFormMixin, ImageFormMixin, forms.ModelForm):
    class Meta:
        model = Teacher
        fields = [
            "department",
            "left_on",
            "first_name",
            "last_name",
            "employee_number",
            "email",
            "phone",
            "qualification",
            "joined_on",
            "is_active",
            "photo",
        ]


class StaffForm(EmploymentFormMixin, StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Staff
        fields = [
            "department",
            "left_on",
            "first_name",
            "last_name",
            "employee_number",
            "job_title",
            "email",
            "phone",
            "joined_on",
            "is_active",
        ]


DIRECTORY_FORMS = {"guardians": GuardianForm, "teachers": TeacherForm, "staff": StaffForm}


class CSVUploadForm(StyledFormMixin, forms.Form):
    file = forms.FileField(
        label="Admissions CSV",
        help_text="UTF-8 CSV, up to 500 students and 1 MB. "
        "Download the template to see the required columns.",
    )


class ImportConfirmForm(StyledFormMixin, forms.Form):
    confirm = forms.BooleanField(label="I reviewed every row and confirm these admissions.")
