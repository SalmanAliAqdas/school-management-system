from django import forms
from django.forms import formset_factory, modelform_factory

from academics.models import AcademicYear, ClassSubject, Section, Subject, Term
from core.form_mixins import StyledFormMixin
from people.models import Teacher

from .models import (
    Assessment,
    AssessmentType,
    ExamCohort,
    ExamController,
    ExaminationSettings,
    ExamRoom,
    ExamSession,
    ExamSubject,
    GradeBand,
    GradingPolicy,
    MarkEntry,
    SessionContribution,
)
from .selectors import capable, sessions_visible_to

SETUP = {
    "types": (AssessmentType, "Assessment types", ["name", "description", "is_active"]),
    "rooms": (ExamRoom, "Examination rooms", ["name"]),
    "policies": (
        GradingPolicy,
        "Grading policies",
        [
            "academic_year",
            "name",
            "overall_pass",
            "require_subject_pass",
            "absence_rule",
            "exemption_rule",
            "optional_rule",
            "decimal_places",
            "independent_review",
            "principal_approval",
        ],
    ),
    "bands": (
        GradeBand,
        "Grade bands",
        ["policy", "lower", "upper", "label", "description", "points"],
    ),
    "sessions": (
        ExamSession,
        "Examination sessions",
        [
            "academic_year",
            "term",
            "assessment_type",
            "policy",
            "name",
            "description",
            "retake_of",
            "starts_on",
            "ends_on",
            "eligibility_on",
            "report_kind",
        ],
    ),
    "cohorts": (ExamCohort, "Classes and sections", ["session", "section"]),
    "subjects": (
        ExamSubject,
        "Subject structures",
        ["cohort", "subject", "weight", "passing_percentage", "required"],
    ),
    "assessments": (
        Assessment,
        "Assessment components",
        [
            "exam_subject",
            "assessment_type",
            "name",
            "component",
            "max_marks",
            "weight",
            "passing_percentage",
            "require_pass",
            "optional",
        ],
    ),
    "controllers": (ExamController, "Examination controllers", ["session", "user"]),
    "sources": (
        SessionContribution,
        "Term / annual report sources",
        ["session", "source", "weight"],
    ),
    "settings": (
        ExaminationSettings,
        "Ranking and academic support settings",
        [
            "ranking_enabled",
            "ranking_scope",
            "ranking_ties",
            "ranking_pass_only",
            "support_threshold",
        ],
    ),
}


class SetupFormBase(StyledFormMixin, forms.ModelForm):
    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        sessions = sessions_visible_to(actor)
        if not capable(actor, "view_all_examinations"):
            sessions = sessions.filter(controllers=actor)
        if "academic_year" in self.fields:
            self.fields["academic_year"].queryset = AcademicYear.objects.filter(status="open")
        if "term" in self.fields:
            self.fields["term"].queryset = Term.objects.filter(
                status="open", academic_year__status="open"
            )
        if "session" in self.fields:
            self.fields["session"].queryset = sessions.filter(state="draft")
        if "cohort" in self.fields:
            self.fields["cohort"].queryset = ExamCohort.objects.filter(
                session__in=sessions, session__state="draft"
            )
        if "exam_subject" in self.fields:
            self.fields["exam_subject"].queryset = ExamSubject.objects.filter(
                cohort__session__in=sessions, cohort__session__state="draft"
            ).select_related("cohort__section__school_class", "subject")
        if "policy" in self.fields:
            self.fields["policy"].queryset = GradingPolicy.objects.filter(
                academic_year__status="open"
            )
        if "source" in self.fields:
            self.fields["source"].queryset = sessions.filter(state__in=["published", "archived"])
        if "retake_of" in self.fields:
            self.fields["retake_of"].queryset = sessions.filter(
                state__in=["published", "archived"], report_kind="assessment"
            )
        if "user" in self.fields:
            from django.contrib.auth import get_user_model

            self.fields["user"].queryset = (
                get_user_model()
                .objects.filter(
                    is_active=True,
                    groups__permissions__content_type__app_label="examinations",
                    groups__permissions__codename="review_results",
                )
                .distinct()
            )
        if "subject" in self.fields:
            self.fields["subject"].queryset = Subject.objects.filter(
                pk__in=ClassSubject.objects.values("subject_id")
            )
        if "section" in self.fields:
            self.fields["section"].queryset = Section.objects.select_related("school_class")


def setup_form(kind):
    model, _, fields = SETUP[kind]
    return modelform_factory(model, form=SetupFormBase, fields=fields)


class ActionForm(StyledFormMixin, forms.Form):
    expected_version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    reason = forms.CharField(max_length=1000, widget=forms.Textarea(attrs={"rows": 2}))
    confirm = forms.BooleanField(label="I confirm this action and have reviewed the records.")


class ReviewForm(ActionForm):
    decision = forms.ChoiceField(
        choices=[
            ("review", "Begin review"),
            ("return", "Return to teacher"),
            ("approve", "Approve marks sheet"),
        ]
    )


class ScheduleForm(StyledFormMixin, forms.Form):
    assessment = forms.ModelChoiceField(queryset=Assessment.objects.none())
    starts_at = forms.DateTimeField(widget=forms.DateTimeInput(attrs={"type": "datetime-local"}))
    ends_at = forms.DateTimeField(widget=forms.DateTimeInput(attrs={"type": "datetime-local"}))
    room = forms.ModelChoiceField(queryset=ExamRoom.objects.all(), required=False)
    invigilators = forms.ModelMultipleChoiceField(
        queryset=Teacher.objects.filter(is_active=True), required=False
    )

    def __init__(self, *args, session, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assessment"].queryset = Assessment.objects.filter(
            exam_subject__cohort__session=session
        ).select_related("exam_subject__cohort__section__school_class", "exam_subject__subject")


class MarkRow(StyledFormMixin, forms.Form):
    candidate = forms.UUIDField(widget=forms.HiddenInput)
    status = forms.ChoiceField(choices=MarkEntry.Status.choices)
    marks = forms.DecimalField(
        max_digits=9,
        decimal_places=3,
        min_value=0,
        required=False,
        widget=forms.NumberInput(attrs={"step": "0.001"}),
    )
    remarks = forms.CharField(max_length=500, required=False)


MarkRows = formset_factory(MarkRow, extra=0, max_num=1500, validate_max=True, absolute_max=1500)


class MarksActionForm(forms.Form):
    expected_version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    action = forms.ChoiceField(
        choices=[("draft", "Save draft"), ("submit", "Submit for review")], widget=forms.HiddenInput
    )


class CorrectionForm(StyledFormMixin, forms.Form):
    status = forms.ChoiceField(choices=MarkEntry.Status.choices)
    marks = forms.DecimalField(max_digits=9, decimal_places=3, min_value=0, required=False)
    remarks = forms.CharField(max_length=500, required=False)
    reason = forms.CharField(max_length=1000, widget=forms.Textarea(attrs={"rows": 3}))
    confirm = forms.BooleanField(label="Request independent review of these revised marks.")


class CorrectionDecisionForm(StyledFormMixin, forms.Form):
    approve = forms.ChoiceField(
        choices=[
            ("yes", "Approve correction and issue revised results"),
            ("no", "Reject correction"),
        ]
    )
    reason = forms.CharField(max_length=1000, widget=forms.Textarea(attrs={"rows": 3}))
    confirm = forms.BooleanField(label="I reviewed the original and proposed marks.")


class CandidateForm(StyledFormMixin, forms.Form):
    expected_version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    teacher_remarks = forms.CharField(
        max_length=1000, required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    principal_remarks = forms.CharField(
        max_length=1000, required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    withheld = forms.BooleanField(required=False)
    withholding_reason = forms.CharField(max_length=500, required=False)


class AmendmentForm(CandidateForm):
    reason = forms.CharField(max_length=1000, widget=forms.Textarea(attrs={"rows": 3}))
    confirm = forms.BooleanField(
        label="Request independent review; retain earlier report versions."
    )


class RecommendationForm(StyledFormMixin, forms.Form):
    eligible = forms.ChoiceField(
        choices=[("yes", "Recommend eligibility"), ("no", "Recommend academic review")]
    )
    reason = forms.CharField(max_length=1000, widget=forms.Textarea(attrs={"rows": 3}))
    confirm = forms.BooleanField(label="This recommendation does not promote the student.")
