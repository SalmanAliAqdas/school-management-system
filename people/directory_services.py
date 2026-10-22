from contextlib import nullcontext

from django.core.exceptions import ValidationError
from django.db import transaction

from audit.services import record_event
from core.operations import require_capability
from core.uploads import image_write

from .models import GuardianStudent, Student, Teacher


@transaction.atomic
def save_profile(actor, form):
    model = form._meta.model
    verb = "change" if form.instance.pk else "add"
    require_capability(actor, f"people.{verb}_{model._meta.model_name}")
    if form.instance.pk:
        model.objects.select_for_update().get(pk=form.instance.pk)
    obj = form.save(commit=False)
    if (
        isinstance(obj, Teacher)
        and obj.pk
        and not obj.is_active
        and obj.assignments.filter(academic_year__status="open").exists()
    ):
        raise ValidationError(
            "This teacher has assignments in an open year. "
            "Resolve these before deactivating the profile."
        )
    obj.full_clean()
    with image_write(obj, "photo") if isinstance(obj, Teacher) else nullcontext():
        obj.save()
        record_event(f"{model._meta.model_name}.{verb}", actor=actor, target=obj.pk)
    return obj


@transaction.atomic
def save_guardian_link(actor, form):
    verb = "change" if form.instance.pk else "add"
    require_capability(actor, f"people.{verb}_guardianstudent", student_scope=True)
    student = Student.objects.select_for_update().get(pk=form.cleaned_data["student"].pk)
    if not student.is_active:
        raise ValidationError("Guardian relationships on inactive student records are protected.")
    if form.instance.pk:
        original = GuardianStudent.objects.select_for_update().get(pk=form.instance.pk)
        if (
            original.student_id != student.pk
            or original.guardian_id != form.cleaned_data["guardian"].pk
        ):
            raise ValidationError(
                "Change the relationship description here. "
                "Remove and create a link to change the linked person."
            )
    obj = form.save()
    record_event(f"guardian_link.{verb}", actor=actor, target=obj.pk)
    return obj


@transaction.atomic
def remove_guardian_link(actor, pk):
    require_capability(actor, "people.delete_guardianstudent", student_scope=True)
    link = GuardianStudent.objects.get(pk=pk)
    student = Student.objects.select_for_update().get(pk=link.student_id)
    if not student.is_active:
        raise ValidationError("Guardian relationships on inactive student records are protected.")
    link.delete()
    record_event("guardian_link.removed", actor=actor, target=f"{student.pk}:{link.guardian_id}")
