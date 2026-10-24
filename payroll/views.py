from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from core.branding import school_branding
from finance.exports import pdf_document

from .forms import GenerateForm
from .models import PayrollRun, Payslip
from .services import generate, record_payment, transition


def visible(user):
    rows = Payslip.objects.select_related("employee", "run__period")
    return (
        rows
        if user.has_perm("payroll.view_all_payroll")
        else rows.filter(employee__user=user, state__in=["released", "paid"])
    )


@login_required
def overview(request):
    rows = visible(request.user)
    if not rows.exists() and not request.user.has_perm("payroll.manage_payroll"):
        raise PermissionDenied
    return render(
        request,
        "operations/phase8_dashboard.html",
        {
            "title": "Payroll",
            "description": (
                "Confidential salary preparation, approval, finance posting and released payslips."
            ),
            "metrics": [
                (
                    "Payroll runs",
                    PayrollRun.objects.count()
                    if request.user.has_perm("payroll.view_all_payroll")
                    else rows.values("run").distinct().count(),
                ),
                ("Visible payslips", rows.count()),
            ],
            "sections": [
                {
                    "title": "Payslips",
                    "help": "Draft and held payroll is never exposed to employees.",
                    "headings": ["Reference", "Period", "Employee", "Net", "Status"],
                    "rows": [
                        (
                            r.reference,
                            r.run.period.name,
                            r.employee.name,
                            r.net,
                            r.get_state_display(),
                        )
                        for r in rows[:50]
                    ],
                }
            ],
        },
    )


@login_required
def payslip(request, pk):
    row = get_object_or_404(visible(request.user), pk=pk)
    return pdf_document(
        "Payslip",
        school_branding(),
        ["Component", "Kind", "Amount"],
        [(x.name, x.kind.title(), x.amount) for x in row.lines.all()],
        identity=(
            ("Employee", row.employee.name),
            ("Employee code", row.employee.employee_code),
            ("Period", row.run.period.name),
            ("Reference", row.reference),
            ("Gross", row.gross),
            ("Deductions", row.deductions),
            ("Net", row.net),
        ),
        status=row.get_state_display(),
        filename=f"payslip-{row.reference}.pdf",
    )


@login_required
@require_http_methods(["GET", "POST"])
def generate_view(request):
    if not request.user.has_perm("payroll.manage_payroll"):
        raise PermissionDenied
    form = GenerateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        generate(request.user, form.cleaned_data["period"], form.cleaned_data["employees"])
        messages.success(request, "Draft payroll generated.")
        return redirect("payroll:overview")
    return render(
        request,
        "operations/phase7_form.html",
        {
            "title": "Generate draft payroll",
            "hint": (
                "Effective components and employment dates are snapshotted using Decimal "
                "calculations."
            ),
            "form": form,
        },
    )


@login_required
@require_POST
def action(request, pk, action_name):
    transition(request.user, pk, action_name, request.POST.get("reason", ""))
    messages.success(request, f"Payroll {action_name} completed.")
    return redirect("payroll:overview")


@login_required
@require_POST
def payment(request, pk):
    record_payment(request.user, pk)
    messages.success(request, "Payroll payment recorded.")
    return redirect("payroll:overview")
