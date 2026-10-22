from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from academics.models import AcademicYear, SchoolClass, Section
from audit.services import record_event
from core.operations import positive_id

from .selectors import enrollments_visible_to, students_visible_to


@login_required
@permission_required("people.view_student", raise_exception=True)
@require_GET
def student_list(request):
    students = students_visible_to(request.user)
    query = request.GET.get("q", "").strip()[:100]
    status = request.GET.get("status", "")
    if query:
        students = students.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(admission_number__icontains=query)
        )
    if status in {"active", "inactive"}:
        students = students.filter(is_active=(status == "active"))
    elif status in {"enrolled", "withdrawn", "transferred", "graduated"}:
        students = students.filter(status=status)
    placements = enrollments_visible_to(request.user)
    filtered = False
    for key, lookup in (
        ("year", "academic_year_id"),
        ("section", "section_id"),
        ("class", "section__school_class_id"),
    ):
        value = request.GET.get(key, "")
        if value:
            placements = placements.filter(**{lookup: positive_id(value)})
            filtered = True
    if filtered:
        students = students.filter(pk__in=placements.values("student_id"))
    sort = request.GET.get("sort", "name")
    ordering = {
        "name": ["first_name", "last_name"],
        "-name": ["-first_name", "-last_name"],
        "admission": ["admission_number"],
        "newest": ["-admission_date"],
    }.get(sort, ["first_name", "last_name"])
    students = students.order_by(*ordering, "pk")
    students = students.prefetch_related(
        Prefetch(
            "enrollments",
            queryset=enrollments_visible_to(request.user),
            to_attr="visible_enrollments",
        )
    )
    page = Paginator(students, 20).get_page(request.GET.get("page"))
    return render(
        request,
        "people/student_list.html",
        {
            "page_obj": page,
            "query": query,
            "status_filter": status,
            "active_nav": "students",
            "years": AcademicYear.objects.filter(
                pk__in=enrollments_visible_to(request.user).values("academic_year_id")
            ),
            "classes": SchoolClass.objects.filter(
                sections__enrollments__in=enrollments_visible_to(request.user)
            ).distinct(),
            "sections": Section.objects.filter(
                pk__in=enrollments_visible_to(request.user).values("section_id")
            ),
            "sort": sort,
        },
    )


@login_required
@permission_required("people.view_student", raise_exception=True)
@require_GET
def student_detail(request, pk):
    student = get_object_or_404(students_visible_to(request.user), pk=pk)
    enrollments = enrollments_visible_to(request.user).filter(student=student)
    record_event("student.viewed", actor=request.user, target=student.pk)
    can_see_guardians = (
        request.user.has_perm("people.view_all_students")
        or student.user_id == request.user.pk
        or student.guardian_links.filter(guardian__user=request.user).exists()
    )
    return render(
        request,
        "people/student_detail.html",
        {
            "student": student,
            "enrollments": enrollments,
            "active_nav": "students",
            "guardians": student.guardian_links.select_related("guardian")
            if can_see_guardians
            else [],
        },
    )
