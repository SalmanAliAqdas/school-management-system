import csv
from io import StringIO

from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from attendance.exports import safe_csv
from attendance.models import StudentAttendance
from attendance.reporting import summary
from audit.services import record_event
from core.branding import school_branding
from examinations.models import PublishedResult
from finance.exports import pdf_document
from learning.models import Feedback, Submission
from people.models import Enrollment, Student
from portals.selectors import personal_students, teacher_students

from .forms import AnalyticsFilterForm
from .registry import KPI_DEFINITIONS
from .selectors import data_quality, executive_metrics, reporting_rows

REPORTS = [
    ("Students and admissions", "students", "people.view_all_students"),
    ("Attendance", "/attendance/reports/students/", "attendance.view_all_attendance"),
    ("Examinations", "/examinations/results/", "examinations.view_all_examinations"),
    ("Homework", "/learning/", "learning.manage_learning"),
    ("Finance", "/finance/reports/", "finance.view_finance_reports"),
    ("Payroll", "/payroll/", "payroll.view_all_payroll"),
    ("Human resources", "/hr/", "hr.view_all_hr"),
    ("Library", "library", "library.view_all_library"),
    ("Transport", "/transport/", "transport.view_all_transport"),
    ("Inventory", "inventory", "inventory.view_all_inventory"),
    ("Certificates", "certificates", "certificates.view_all_certificates"),
]


def _filters(request):
    form = AnalyticsFilterForm(request.GET or None)
    if not form.is_valid():
        return form, None
    return form, form.cleaned_data


@login_required
@permission_required("core.view_executive_analytics", raise_exception=True)
def executive(request):
    form, values = _filters(request)
    metrics = executive_metrics(request.user, **values) if values else None
    return render(
        request,
        "analytics/executive.html",
        {"form": form, "metrics": metrics, "definitions": KPI_DEFINITIONS, "filters": values},
    )


@login_required
@permission_required("core.view_reporting_center", raise_exception=True)
def center(request):
    available = []
    for label, target, permission in REPORTS:
        if request.user.has_perm(permission):
            available.append((label, target, not target.startswith("/")))
    return render(request, "analytics/center.html", {"reports": available})


@login_required
@permission_required("core.view_reporting_center", raise_exception=True)
def report(request, category):
    permitted = {
        target: permission for _label, target, permission in REPORTS if not target.startswith("/")
    }
    if category not in permitted or not request.user.has_perm(permitted[category]):
        raise PermissionDenied
    form, values = _filters(request)
    rows, headings = reporting_rows(category, **values) if values else ([], [])
    output = request.GET.get("format")
    if output in ("csv", "pdf"):
        if not request.user.has_perm("core.export_analytics"):
            raise PermissionDenied
        if len(rows) >= 5000:
            form.add_error(None, "Narrow the report below 5,000 rows before exporting.")
        elif output == "csv":
            stream = StringIO()
            writer = csv.writer(stream)
            writer.writerow(headings)
            writer.writerows([[safe_csv(value) for value in row] for row in rows])
            response = HttpResponse(
                stream.getvalue().encode("utf-8-sig"), content_type="text/csv; charset=utf-8"
            )
            response["Content-Disposition"] = f'attachment; filename="schoolos-{category}.csv"'
            response["Cache-Control"] = "private, no-store"
            record_event("analytics.export_csv", actor=request.user, target=category)
            return response
        else:
            record_event("analytics.export_pdf", actor=request.user, target=category)
            return pdf_document(
                f"{category.title()} report",
                school_branding(),
                headings,
                rows,
                filename=f"schoolos-{category}.pdf",
            )
    return render(
        request,
        "analytics/report.html",
        {"form": form, "category": category, "headings": headings, "rows": rows[:100]},
    )


@login_required
@permission_required("core.view_data_quality", raise_exception=True)
def quality(request):
    form, values = _filters(request)
    findings = data_quality(values["academic_year"]) if values and values["academic_year"] else []
    return render(request, "analytics/quality.html", {"form": form, "findings": findings})


def _student_scope(user):
    if user.has_perm("people.view_all_students"):
        return Student.objects.all()
    if user.has_perm("accounts.access_student_dashboard"):
        return personal_students(user, "student")
    if user.has_perm("accounts.access_parent_dashboard"):
        return personal_students(user, "parent")
    if user.has_perm("accounts.access_teacher_dashboard"):
        return teacher_students(user)
    return Student.objects.none()


@login_required
def student_progress(request, pk):
    student = get_object_or_404(_student_scope(request.user), pk=pk)
    placements = Enrollment.objects.filter(student=student).select_related(
        "academic_year", "section__school_class"
    )
    attendance = StudentAttendance.objects.filter(
        student=student, register__state="final"
    ).select_related("register__policy")
    publications = PublishedResult.objects.filter(candidate__student=student).select_related(
        "publication__session"
    )
    submissions = Submission.objects.filter(student=student).select_related("assignment")
    released = Feedback.objects.filter(submission__student=student, released=True).select_related(
        "submission__assignment"
    )
    return render(
        request,
        "analytics/student_progress.html",
        {
            "student": student,
            "placements": placements,
            "attendance": summary(attendance),
            "publications": publications,
            "submissions": submissions,
            "feedback": released,
        },
    )
