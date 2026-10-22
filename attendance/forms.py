from django import forms
from django.forms import formset_factory

from academics.models import AcademicYear, SchoolClass, Section
from core.form_mixins import StyledFormMixin
from people.models import Staff, Student, Teacher
from people.selectors import enrollments_visible_to, students_visible_to

from .calendar import school_now
from .models import AttendancePolicy, CalendarEvent, StaffStatus, StudentStatus
from .selectors import sections_markable_by


class RegisterSelectionForm(StyledFormMixin, forms.Form):
    academic_year = forms.ModelChoiceField(queryset=AcademicYear.objects.all())
    school_class = forms.ModelChoiceField(
        queryset=SchoolClass.objects.none(), required=False, label="Class"
    )
    section = forms.ModelChoiceField(queryset=AcademicYear.objects.none(), required=False)
    date = forms.DateField(initial=lambda: school_now().date())

    def __init__(self, *args, actor, staff=False, **kwargs):
        super().__init__(*args, **kwargs)
        selected = self.data.get("academic_year") or self.initial.get("academic_year")
        try:
            year = AcademicYear.objects.filter(pk=int(selected)).first()
        except (TypeError, ValueError, OverflowError):
            year = None
        if staff:
            del self.fields["section"]
            del self.fields["school_class"]
        else:
            self.fields["section"].required = True
            self.fields["section"].queryset = (
                sections_markable_by(actor, year)
                if year
                else sections_markable_by(actor, None).none()
            )
            self.fields["school_class"].queryset = SchoolClass.objects.filter(
                sections__in=self.fields["section"].queryset
            ).distinct()

    def clean(self):
        data = super().clean()
        if (
            data.get("school_class")
            and data.get("section")
            and data["section"].school_class_id != data["school_class"].pk
        ):
            self.add_error("section", "Choose a section in the selected class.")
        return data


class RegisterRowForm(StyledFormMixin, forms.Form):
    key = forms.CharField(widget=forms.HiddenInput)
    status = forms.ChoiceField(choices=[("", "Not marked"), *StudentStatus.choices], required=False)
    arrival_time = forms.TimeField(required=False, widget=forms.TimeInput(attrs={"type": "time"}))
    notes = forms.CharField(max_length=500, required=False)


class StaffRowForm(RegisterRowForm):
    status = forms.ChoiceField(choices=[("", "Not marked"), *StaffStatus.choices], required=False)


StudentRowSet = formset_factory(
    RegisterRowForm, extra=0, max_num=2000, validate_max=True, absolute_max=2000
)
StaffRowSet = formset_factory(
    StaffRowForm, extra=0, max_num=1000, validate_max=True, absolute_max=1000
)


class RegisterSaveForm(StyledFormMixin, forms.Form):
    expected_version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    action = forms.ChoiceField(
        choices=[("draft", "Save draft"), ("final", "Finalize register")], widget=forms.HiddenInput
    )
    reason = forms.CharField(
        max_length=500,
        required=False,
        label="Late submission reason",
        help_text="Required for administrator submission after the daily cutoff. "
        "Teachers must submit before cutoff.",
    )
    confirm = forms.BooleanField(
        required=False, label="I have reviewed every row and confirm final submission."
    )

    def clean(self):
        data = super().clean()
        if data.get("action") == "final" and not data.get("confirm"):
            self.add_error("confirm", "Confirm the register before final submission.")
        return data


class CorrectionForm(StyledFormMixin, forms.Form):
    status = forms.ChoiceField(choices=StudentStatus.choices)
    arrival_time = forms.TimeField(required=False, widget=forms.TimeInput(attrs={"type": "time"}))
    notes = forms.CharField(max_length=500, required=False)
    reason = forms.CharField(max_length=500, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, staff=False, **kwargs):
        super().__init__(*args, **kwargs)
        if staff:
            self.fields["status"].choices = StaffStatus.choices


class DecisionForm(StyledFormMixin, forms.Form):
    decision = forms.ChoiceField(choices=[("approve", "Approve"), ("reject", "Reject")])
    reason = forms.CharField(
        max_length=500, required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    confirm = forms.BooleanField(
        label="I confirm this decision and the attendance changes described above."
    )

    def clean(self):
        data = super().clean()
        if data.get("decision") == "reject" and not data.get("reason"):
            self.add_error("reason", "A rejection reason is required.")
        return data


class PolicyForm(StyledFormMixin, forms.ModelForm):
    working_weekdays = forms.TypedMultipleChoiceField(
        choices=[
            (i, day)
            for i, day in enumerate(
                ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            )
        ],
        coerce=int,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = AttendancePolicy
        fields = [
            "academic_year",
            "effective_from",
            "working_weekdays",
            "late_after",
            "cutoff_time",
            "late_credit",
            "exclude_excused",
            "correction_window_days",
            "low_attendance_threshold",
            "enforce_terms",
        ]
        widgets = {
            "late_after": forms.TimeInput(attrs={"type": "time"}),
            "cutoff_time": forms.TimeInput(attrs={"type": "time"}),
        }


class CalendarEventForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = CalendarEvent
        fields = ["academic_year", "title", "kind", "applies_to", "starts_on", "ends_on", "reason"]


class LeaveForm(StyledFormMixin, forms.Form):
    academic_year = forms.ModelChoiceField(queryset=AcademicYear.objects.filter(status="open"))
    person = forms.ChoiceField()
    starts_on = forms.DateField()
    ends_on = forms.DateField()
    kind = forms.ChoiceField(
        choices=[("sick", "Sick leave"), ("casual", "Casual leave"), ("annual", "Annual leave")]
    )
    reason = forms.CharField(max_length=500, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        teachers, staff = (
            Teacher.objects.all(),
            Staff.objects.exclude(user__isnull=False, user__teacher_profile__isnull=False),
        )
        if not actor.has_perm("attendance.manage_staff_attendance"):
            teachers, staff = teachers.filter(user=actor), staff.filter(user=actor)
        self.people = {
            **{f"teacher:{p.pk}": p for p in teachers},
            **{f"staff:{p.pk}": p for p in staff},
        }
        self.fields["person"].choices = [
            (key, f"{person} · {person.employee_number}") for key, person in self.people.items()
        ]


class ReportFilterForm(StyledFormMixin, forms.Form):
    academic_year = forms.ModelChoiceField(queryset=AcademicYear.objects.all())
    period = forms.ChoiceField(
        choices=[
            ("month", "Monthly"),
            ("day", "Daily"),
            ("week", "Weekly"),
            ("year", "Academic year"),
            ("custom", "Custom dates"),
        ],
        required=False,
    )
    date = forms.DateField(required=False)
    starts_on = forms.DateField(required=False)
    ends_on = forms.DateField(required=False)
    section = forms.ModelChoiceField(queryset=Section.objects.none(), required=False)
    school_class = forms.ModelChoiceField(
        queryset=SchoolClass.objects.none(), required=False, label="Class"
    )
    employee = forms.ChoiceField(required=False)
    student = forms.ModelChoiceField(queryset=Student.objects.none(), required=False)
    status = forms.ChoiceField(
        choices=[("", "All statuses"), *StaffStatus.choices, ("excused", "Excused")], required=False
    )
    department = forms.CharField(max_length=80, required=False)
    q = forms.CharField(max_length=100, required=False, label="Search")
    sort = forms.ChoiceField(
        choices=[("date", "Newest date"), ("name", "Name"), ("percentage", "Lowest percentage")],
        required=False,
    )

    def __init__(self, *args, actor, staff=False, compact=False, personal=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["student"].queryset = students_visible_to(actor)
        self.fields["section"].queryset = Section.objects.filter(
            pk__in=enrollments_visible_to(actor).values("section_id")
        ).select_related("school_class")
        self.fields["school_class"].queryset = SchoolClass.objects.filter(
            sections__in=self.fields["section"].queryset
        ).distinct()
        teachers, staff_people = (
            Teacher.objects.all(),
            Staff.objects.exclude(user__isnull=False, user__teacher_profile__isnull=False),
        )
        if not actor.has_perm("attendance.view_all_staff_attendance"):
            teachers, staff_people = teachers.filter(user=actor), staff_people.filter(user=actor)
        self.fields["employee"].choices = [
            ("", "All authorized employees"),
            *[(f"teacher:{person.pk}", str(person)) for person in teachers],
            *[(f"staff:{person.pk}", str(person)) for person in staff_people],
        ]
        if compact:
            self.fields = {name: self.fields[name] for name in ("academic_year", "date")}
        elif personal:
            self.fields = {
                name: self.fields[name]
                for name in ("academic_year", "period", "date", "starts_on", "ends_on", "sort")
            }
        else:
            for name in (
                ["student", "school_class", "section"] if staff else ["employee", "department"]
            ):
                self.fields.pop(name)
            self.fields["status"].choices = [
                ("", "All statuses"),
                *(StaffStatus.choices if staff else StudentStatus.choices),
            ]


class CalendarCancelForm(StyledFormMixin, forms.Form):
    reason = forms.CharField(max_length=500, widget=forms.Textarea(attrs={"rows": 3}))
    confirm = forms.BooleanField(
        label="Cancel this calendar exception and retain its audit history."
    )
