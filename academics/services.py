from django.core.exceptions import ValidationError
from django.db import transaction

from audit.services import record_event
from core.models import SchoolSettings
from core.operations import require_capability

from .models import (
    AcademicYear,
    ClassSubject,
    SchoolClass,
    Section,
    Subject,
    TeachingAssignment,
    Term,
)


def protect_academic_edit(instance):
    """Prevent renaming/re-dating references that already describe academic history."""
    if not instance.pk:
        return
    protected = False
    if isinstance(instance, AcademicYear):
        protected = (
            instance.status != "open"
            or instance.enrollments.exists()
            or instance.terms.exists()
            or instance.teaching_assignments.exists()
            or ClassSubject.objects.filter(academic_year=instance).exists()
        )
    elif isinstance(instance, Term):
        protected = instance.status != "open" or instance.academic_year.status != "open"
        from attendance.models import StudentRegister

        protected = (
            protected
            or StudentRegister.objects.filter(academic_year=instance.academic_year).exists()
        )
    elif isinstance(instance, SchoolClass):
        protected = (
            instance.sections.filter(enrollments__isnull=False).exists()
            or instance.sections.filter(teaching_assignments__isnull=False).exists()
            or ClassSubject.objects.filter(school_class=instance).exists()
        )
    elif isinstance(instance, Section):
        protected = instance.enrollments.exists() or instance.teaching_assignments.exists()
    elif isinstance(instance, Subject):
        protected = (
            instance.teaching_assignments.exists()
            or ClassSubject.objects.filter(subject=instance).exists()
        )
    elif isinstance(instance, TeachingAssignment):
        protected = instance.academic_year.status != "open"
    elif isinstance(instance, ClassSubject):
        protected = (
            instance.academic_year.status != "open"
            or TeachingAssignment.objects.filter(
                academic_year=instance.academic_year,
                section__school_class=instance.school_class,
                subject=instance.subject,
            ).exists()
        )
    if protected:
        raise ValidationError(
            "This academic record is in use or closed. Its historical definition is protected; "
            "create a new record instead."
        )


@transaction.atomic
def save_academic(actor, form):
    model = form._meta.model
    verb = "change" if form.instance.pk else "add"
    require_capability(actor, f"academics.{verb}_{model._meta.model_name}")
    SchoolSettings.objects.get_or_create(pk=1)
    SchoolSettings.objects.select_for_update().get(pk=1)
    if form.instance.pk:
        original = model.objects.select_for_update().get(pk=form.instance.pk)
        protect_academic_edit(original)
    instance = form.save(commit=False)
    if hasattr(instance, "academic_year"):
        year = AcademicYear.objects.select_for_update().get(pk=instance.academic_year_id)
        if year.status != "open":
            raise ValidationError("Choose an open academic year.")
    if isinstance(instance, TeachingAssignment):
        if not instance.teacher.is_active:
            raise ValidationError("Choose an active teacher.")
        if not ClassSubject.objects.filter(
            academic_year=instance.academic_year,
            school_class=instance.section.school_class,
            subject=instance.subject,
        ).exists():
            raise ValidationError("Assign this subject to the class and academic year first.")
    instance.full_clean()
    instance.save()
    record_event(f"academic.{verb}", actor=actor, target=f"{model._meta.model_name}:{instance.pk}")
    return instance


@transaction.atomic
def period_action(actor, kind, pk, action):
    model = {"years": AcademicYear, "terms": Term}[kind]
    require_capability(actor, f"academics.change_{model._meta.model_name}")
    SchoolSettings.objects.get_or_create(pk=1)
    SchoolSettings.objects.select_for_update().get(pk=1)
    if model is Term:
        year_id = Term.objects.get(pk=pk).academic_year_id
        parent = AcademicYear.objects.select_for_update().get(pk=year_id)
        if parent.status != "open":
            raise ValidationError("The parent academic year is closed or archived.")
    period = model.objects.select_for_update().get(pk=pk)
    if action == "activate":
        if period.status != "open":
            raise ValidationError("Closed and archived periods cannot be reactivated.")
        others = model.objects.all()
        if model is Term:
            others = others.filter(academic_year=period.academic_year)
        others.filter(is_current=True).update(is_current=False)
        period.is_current = True
    elif action == "close":
        if period.status != "open":
            raise ValidationError("Only an open period can be closed.")
        if model is AcademicYear and period.enrollments.filter(is_active=True).exists():
            raise ValidationError(
                "Resolve active enrollments through promotion, transfer out, withdrawal or "
                "graduation before closing this year."
            )
        if model is AcademicYear:
            from attendance.models import StaffRegister, StudentRegister

            if (
                StudentRegister.objects.filter(academic_year=period, state="draft").exists()
                or StaffRegister.objects.filter(academic_year=period, state="draft").exists()
            ):
                raise ValidationError(
                    "Finalize outstanding attendance registers before closing this academic year."
                )
        period.status, period.is_current = "closed", False
        if model is AcademicYear:
            period.terms.filter(status="open").update(status="closed", is_current=False)
    elif action == "archive":
        if period.status != "closed":
            raise ValidationError("Close this period before archiving it.")
        period.status, period.is_current = "archived", False
        if model is AcademicYear:
            period.terms.update(status="archived", is_current=False)
    else:
        raise ValidationError("Choose a supported period action.")
    period.full_clean()
    period.save()
    record_event(f"academic.{action}", actor=actor, target=f"{kind}:{pk}")
    return period
