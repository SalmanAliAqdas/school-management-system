from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from .forms import EmployeeForm, EmploymentForm
from .models import Department, Employee, StaffDocument
from .services import employment_change, require_hr


@login_required
def overview(request):
    own = Employee.objects.filter(user=request.user)
    rows = (
        Employee.objects.select_related("staff", "teacher")
        if request.user.has_perm("hr.view_all_hr")
        else own
    )
    if not rows.exists() and not request.user.has_perm("hr.manage_hr"):
        raise PermissionDenied
    return render(
        request,
        "operations/phase8_dashboard.html",
        {
            "title": "Human resources",
            "description": (
                "Effective-dated employment, confidential development records and "
                "existing attendance/leave integration."
            ),
            "metrics": [
                ("Employees", rows.count()),
                ("Departments", Department.objects.filter(is_active=True).count()),
            ],
            "sections": [
                {
                    "title": "Employees",
                    "help": "Only records permitted to this account are shown.",
                    "headings": ["Code", "Employee", "Status"],
                    "rows": [(r.employee_code, r.name, r.get_status_display()) for r in rows[:50]],
                }
            ],
        },
    )


@login_required
def document(request, pk):
    row = get_object_or_404(StaffDocument.objects.select_related("employee"), pk=pk)
    require_hr(request.user, row.employee)
    response = HttpResponse(bytes(row.content), content_type=row.content_type)
    response["Content-Disposition"] = f'attachment; filename="{row.filename}"'
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
@require_http_methods(["GET", "POST"])
def employee_new(request):
    if not request.user.has_perm("hr.manage_hr"):
        raise PermissionDenied
    form = EmployeeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Employee profile created.")
        return redirect("hr:overview")
    return render(
        request,
        "operations/phase7_form.html",
        {
            "title": "Create employee profile",
            "hint": "Choose exactly one existing staff or teacher identity.",
            "form": form,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def employment(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    require_hr(request.user, employee, manage=True)
    form = EmploymentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        employment_change(request.user, employee, **form.cleaned_data)
        messages.success(request, "Employment history updated.")
        return redirect("hr:overview")
    return render(
        request,
        "operations/phase7_form.html",
        {
            "title": "Record employment change",
            "hint": "The previous effective record is closed and retained.",
            "form": form,
        },
    )
