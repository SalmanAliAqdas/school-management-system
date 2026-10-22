from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from audit.services import record_event

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
        {"page_obj": page, "query": query, "status_filter": status, "active_nav": "students"},
    )


@login_required
@permission_required("people.view_student", raise_exception=True)
@require_GET
def student_detail(request, pk):
    student = get_object_or_404(students_visible_to(request.user), pk=pk)
    enrollments = enrollments_visible_to(request.user).filter(student=student)
    record_event("student.viewed", actor=request.user, target=student.pk)
    return render(
        request,
        "people/student_detail.html",
        {"student": student, "enrollments": enrollments, "active_nav": "students"},
    )
