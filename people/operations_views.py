import csv
import io
import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from academics.models import AcademicYear, Section
from core.operations import form_errors, positive_id, require_capability

from .directory_services import remove_guardian_link, save_guardian_link, save_profile
from .forms import (
    DIRECTORY_FORMS,
    AdmissionForm,
    CSVUploadForm,
    GuardianLinkForm,
    ImportConfirmForm,
    RollCorrectionForm,
    StudentEditForm,
    TransitionForm,
)
from .imports import CSV_COLUMNS, confirm_import, import_permission, preview_import
from .models import AdmissionImport, Enrollment, GuardianStudent, Teacher
from .selectors import enrollments_visible_to, students_visible_to
from .services import admit_student, correct_roll, transition_student, update_student


def operation_render(request, form, title, **extra):
    return render(
        request,
        "operations/form.html",
        {
            "form": form,
            "title": title,
            "back_url": "people:student_list",
            "active_nav": "students",
            **extra,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def admission(request):
    require_capability(request.user, "people.add_student", student_scope=True)
    form = AdmissionForm(request.POST if request.method == "POST" else None, request.FILES or None)
    if not request.user.has_perm("people.add_guardianstudent"):
        form.fields["guardian"].queryset = form.fields["guardian"].queryset.none()
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            student = admit_student(
                request.user,
                data={name: data[name] for name in form._meta.fields},
                academic_year=data["academic_year"],
                section=data["section"],
                started_on=data["started_on"],
                roll_number=data["roll_number"],
                guardians=[(data["guardian"], data["relationship"])] if data["guardian"] else [],
            )
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(request, f"Admission completed: {student.admission_number}.")
            return redirect("people:student_detail", pk=student.pk)
    return operation_render(
        request,
        form,
        "Admit a student",
        description="Admission numbers are generated automatically. "
        "Existing academic history is retained.",
    )


@login_required
@require_http_methods(["GET", "POST"])
def student_edit(request, pk):
    require_capability(request.user, "people.change_student", student_scope=True)
    student = get_object_or_404(students_visible_to(request.user), pk=pk)
    form = StudentEditForm(
        request.POST if request.method == "POST" else None, request.FILES or None, instance=student
    )
    if request.method == "POST" and form.is_valid():
        try:
            update_student(
                request.user, pk, {name: form.cleaned_data[name] for name in form._meta.fields}
            )
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(request, "Student profile updated.")
            return redirect("people:student_detail", pk=pk)
    return operation_render(
        request,
        form,
        f"Edit {student}",
        description="Admission number, admission date and placement history are protected. "
        "Use the enrollment workflow to change placement.",
    )


@login_required
@require_http_methods(["GET", "POST"])
def student_transition(request, pk):
    require_capability(request.user, "people.transition_students", student_scope=True)
    student = get_object_or_404(students_visible_to(request.user), pk=pk)
    current = Enrollment.objects.filter(student=student, is_active=True).first()
    form = TransitionForm(
        request.POST if request.method == "POST" else None,
        initial={
            "expected_enrollment": current.pk if current else 0,
            "academic_year": current.academic_year_id if current else None,
        },
    )
    if request.method == "POST" and form.is_valid():
        data = {k: v for k, v in form.cleaned_data.items() if k != "confirm"}
        try:
            transition_student(request.user, pk, **data)
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(
                request, "Enrollment updated. The previous placement remains in history."
            )
            return redirect("people:student_detail", pk=pk)
    return operation_render(
        request,
        form,
        f"Enrollment change: {student}",
        description=f"Current placement: {current.section if current else 'none'}. "
        "Review the action and dates carefully before confirming.",
    )


@login_required
@require_http_methods(["GET", "POST"])
def student_roll(request, pk):
    require_capability(request.user, "people.change_student", student_scope=True)
    student = get_object_or_404(students_visible_to(request.user), pk=pk)
    current = Enrollment.objects.filter(student=student, is_active=True).first()
    form = RollCorrectionForm(
        request.POST if request.method == "POST" else None,
        initial={
            "expected_enrollment": current.pk if current else 0,
            "roll_number": current.roll_number if current else "",
        },
    )
    if request.method == "POST" and form.is_valid():
        try:
            correct_roll(
                request.user,
                pk,
                expected_enrollment=form.cleaned_data["expected_enrollment"],
                roll_number=form.cleaned_data["roll_number"],
            )
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(request, "Active roll number corrected.")
            return redirect("people:student_detail", pk=pk)
    return operation_render(
        request,
        form,
        f"Correct active roll: {student}",
        description="Only the active placement's roll number can be corrected. "
        "Historical placements are protected.",
    )


@login_required
@require_GET
def profile_image(request, kind, pk):
    if kind == "students":
        try:
            student_pk = uuid.UUID(pk)
        except ValueError as exc:
            raise Http404 from exc
        obj = get_object_or_404(students_visible_to(request.user), pk=student_pk)
    elif kind == "teachers":
        try:
            teacher_pk = int(pk)
        except ValueError as exc:
            raise Http404 from exc
        records = (
            Teacher.objects.all()
            if request.user.has_perm("people.view_teacher")
            else Teacher.objects.filter(user=request.user)
        )
        obj = get_object_or_404(records, pk=teacher_pk)
    else:
        raise Http404
    if not obj.photo:
        raise Http404
    try:
        response = FileResponse(obj.photo.open("rb"), content_type="image/png")
    except FileNotFoundError as exc:
        raise Http404 from exc
    response["Cache-Control"] = "private, no-store"
    return response


def directory_definition(kind):
    if kind not in DIRECTORY_FORMS:
        raise Http404
    form = DIRECTORY_FORMS[kind]
    return form, form._meta.model


@login_required
@require_GET
def directory_list(request, kind):
    form, model = directory_definition(kind)
    require_capability(request.user, f"people.view_{model._meta.model_name}")
    query = request.GET.get("q", "").strip()[:100]
    records = model.objects.all()
    if query:
        scope = (
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email__icontains=query)
        )
        if "employee_number" in form._meta.fields:
            scope |= Q(employee_number__icontains=query)
        records = records.filter(scope)
    status = request.GET.get("status", "")
    if kind != "guardians" and status in {"active", "inactive"}:
        records = records.filter(is_active=(status == "active"))
    sort = request.GET.get("sort", "name")
    records = records.order_by("-pk" if sort == "newest" else "first_name", "pk")
    return render(
        request,
        "people/directory.html",
        {
            "kind": kind,
            "title": kind.title(),
            "page_obj": Paginator(records, 20).get_page(request.GET.get("page")),
            "query": query,
            "status_filter": status,
            "active_nav": kind,
            "can_add": request.user.has_perm(f"people.add_{model._meta.model_name}"),
        },
    )


@login_required
@require_GET
def directory_detail(request, kind, pk):
    form, model = directory_definition(kind)
    require_capability(request.user, f"people.view_{model._meta.model_name}")
    obj = get_object_or_404(model, pk=pk)
    fields = [
        (model._meta.get_field(name).verbose_name, getattr(obj, name))
        for name in form._meta.fields
        if name != "photo"
    ]
    links = (
        GuardianStudent.objects.filter(guardian=obj).select_related("student")
        if kind == "guardians"
        and request.user.has_perms(
            ["people.view_guardianstudent", "people.view_all_students", "people.view_student"]
        )
        else []
    )
    return render(
        request,
        "people/directory_detail.html",
        {
            "kind": kind,
            "object": obj,
            "fields": fields,
            "links": links,
            "active_nav": kind,
            "assignments": obj.assignments.select_related(
                "academic_year", "section__school_class", "subject"
            )
            if kind == "teachers"
            else [],
            "can_edit": request.user.has_perm(f"people.change_{model._meta.model_name}"),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def directory_edit(request, kind, pk=None):
    form_class, model = directory_definition(kind)
    require_capability(request.user, f"people.{'change' if pk else 'add'}_{model._meta.model_name}")
    obj = get_object_or_404(model, pk=pk) if pk else None
    form = form_class(
        request.POST if request.method == "POST" else None, request.FILES or None, instance=obj
    )
    if request.method == "POST" and form.is_valid():
        try:
            obj = save_profile(request.user, form)
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(request, "Profile saved.")
            return redirect("people:directory_detail", kind=kind, pk=obj.pk)
    return operation_render(
        request,
        form,
        f"{'Edit' if pk else 'Add'} {model._meta.verbose_name}",
        back_url="people:directory",
        back_arg=kind,
        active_nav=kind,
    )


@login_required
@require_http_methods(["GET", "POST"])
def guardian_link(request, pk=None):
    require_capability(
        request.user, f"people.{'change' if pk else 'add'}_guardianstudent", student_scope=True
    )
    obj = get_object_or_404(GuardianStudent, pk=pk) if pk else None
    form = GuardianLinkForm(request.POST if request.method == "POST" else None, instance=obj)
    form.fields["student"].queryset = students_visible_to(request.user).filter(is_active=True)
    if request.method == "POST" and form.is_valid():
        try:
            obj = save_guardian_link(request.user, form)
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(request, "Guardian relationship saved.")
            return redirect("people:student_detail", pk=obj.student_id)
    return operation_render(request, form, "Guardian relationship")


@login_required
@require_http_methods(["GET", "POST"])
def guardian_unlink(request, pk):
    require_capability(request.user, "people.delete_guardianstudent", student_scope=True)
    obj = get_object_or_404(GuardianStudent, pk=pk)
    form = ImportConfirmForm(request.POST if request.method == "POST" else None)
    form.fields[
        "confirm"
    ].label = "I confirm removal of this guardian relationship and its portal access."
    if request.method == "POST" and form.is_valid():
        student_id = obj.student_id
        try:
            remove_guardian_link(request.user, pk)
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(request, "Guardian relationship removed.")
            return redirect("people:student_detail", pk=student_id)
    return operation_render(request, form, f"Remove relationship: {obj.guardian} / {obj.student}")


@login_required
@require_http_methods(["GET", "POST"])
def import_upload(request):
    import_permission(request.user)
    form = CSVUploadForm(request.POST if request.method == "POST" else None, request.FILES or None)
    results, batch = [], None
    if request.method == "POST" and form.is_valid():
        try:
            results, batch = preview_import(request.user, form.cleaned_data["file"])
        except ValidationError as exc:
            form_errors(form, exc)
    return render(
        request,
        "people/import.html",
        {"form": form, "results": results, "batch": batch, "active_nav": "students"},
    )


@login_required
@require_http_methods(["GET", "POST"])
def import_confirm(request, pk):
    import_permission(request.user)
    batch = get_object_or_404(AdmissionImport, pk=pk, actor=request.user)
    form = ImportConfirmForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            count = confirm_import(request.user, pk)
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(request, f"Imported {count} student admissions.")
            return redirect("people:student_list")
    return render(
        request,
        "people/import_confirm.html",
        {"form": form, "batch": batch, "active_nav": "students"},
    )


@login_required
@require_GET
def import_template(request):
    import_permission(request.user)
    output = io.StringIO()
    csv.writer(output).writerow(CSV_COLUMNS)
    response = HttpResponse(output.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="admissions-template.csv"'
    return response


@login_required
@require_GET
def print_student(request, pk, kind):
    if kind not in {"profile", "admission"}:
        raise Http404
    require_capability(request.user, "people.view_student")
    student = get_object_or_404(students_visible_to(request.user), pk=pk)
    guardians = (
        student.guardian_links.select_related("guardian")
        if request.user.has_perm("people.view_all_students")
        or student.user_id == request.user.pk
        or student.guardian_links.filter(guardian__user=request.user).exists()
        else []
    )
    return render(
        request,
        "people/print_student.html",
        {
            "student": student,
            "kind": kind,
            "enrollments": enrollments_visible_to(request.user).filter(student=student),
            "guardians": guardians,
        },
    )


@login_required
@require_GET
def print_class(request):
    require_capability(request.user, "people.view_student")
    # Filter the scoped enrollment queryset first, so prints never infer inaccessible classes.
    rows = (
        enrollments_visible_to(request.user)
        .select_related("student")
        .filter(
            academic_year_id=positive_id(request.GET.get("year")),
            section_id=positive_id(request.GET.get("section")),
        )
    )
    if request.GET.get("status", "active") == "active":
        rows = rows.filter(is_active=True)
    return render(
        request,
        "people/print_class.html",
        {
            "rows": rows.order_by("roll_number", "student__first_name"),
            "year": get_object_or_404(AcademicYear, pk=positive_id(request.GET.get("year")))
            if rows.exists()
            else None,
            "section": get_object_or_404(Section, pk=positive_id(request.GET.get("section")))
            if rows.exists()
            else None,
        },
    )
