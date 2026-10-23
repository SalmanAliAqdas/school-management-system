import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.operations import form_errors

from . import forms
from . import models as m
from .approvals import decide_request, request_action
from .billing import BillingContext, calculate_charges, generate_invoices, issue_invoice
from .common import capable, config, event, fingerprint, initialize, require, school_snapshot
from .exports import pdf_document
from .fines import apply_late_fee
from .ledger import student_balances
from .notifications import send_reminders
from .payments import allocate_credit, collect_payment, invoice_totals, reversal_for
from .reconciliation import pay_expense, request_expense, request_reconciliation
from .reporting import financial_report, statement
from .selectors import (
    invoices_visible_to,
    notices_visible_to,
    payments_visible_to,
    students_visible_to,
)
from .setup import save_setup


def page(request, template, **context):
    context.update(active_nav="finance", finance_settings=config())
    response = render(request, "finance/" + template, context)
    response["Cache-Control"] = "private, no-store"
    return response


def form_page(request, title, form, **context):
    return page(request, "form.html", title=title, form=form, **context)


def paginate(request, rows):
    return Paginator(rows, 25).get_page(request.GET.get("page"))


@login_required
def dashboard(request):
    require(request.user, "access_finance", staff=False)
    if not capable(request.user, "view_all_finance"):
        return redirect("finance:students")
    report = None
    if capable(request.user, "view_finance_reports") and config():
        report = financial_report(request.user)
    return page(
        request,
        "dashboard.html",
        report=report,
        pending=m.FinancialRequest.objects.filter(state="pending").count(),
    )


@login_required
@require_POST
def initialize_view(request):
    initialize(request.user)
    messages.success(
        request,
        "Finance initialized. Configure financial years and periods before recording money.",
    )
    return redirect("finance:dashboard")


@login_required
def setup_list(request, kind):
    if kind not in forms.SETUP:
        raise Http404
    model, title, permission = forms.SETUP[kind]
    require(request.user, permission)
    if kind == "settings":
        return redirect("finance:setup_edit", kind=kind, pk="1")
    rows = model.objects.all().order_by("pk")
    return page(request, "setup.html", title=title, kind=kind, records=paginate(request, rows))


@login_required
def setup_edit(request, kind, pk=None):
    if kind not in forms.SETUP:
        raise Http404
    model, title, permission = forms.SETUP[kind]
    require(request.user, permission)
    instance = get_object_or_404(model, pk=pk) if pk else None
    form = forms.setup_form(kind)(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        try:
            save_setup(request.user, form.save(commit=False))
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(request, "Configuration saved and audited.")
            return (
                redirect("finance:dashboard")
                if kind == "settings"
                else redirect("finance:setup", kind=kind)
            )
    return form_page(request, title, form)


@login_required
def students(request):
    require(request.user, "access_finance", staff=False)
    rows = students_visible_to(request.user).order_by("admission_number")
    if query := request.GET.get("q", "").strip():
        rows = rows.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(admission_number__icontains=query)
        )
    return page(request, "students.html", records=paginate(request, rows))


@login_required
def student_account(request, pk):
    student = get_object_or_404(students_visible_to(request.user), pk=pk)
    date_form = forms.ReportForm(request.GET)
    start = end = None
    if date_form.is_valid():
        start, end = date_form.cleaned_data["start"], date_form.cleaned_data["end"]
    data = statement(student, start=start, end=end)
    balances = student_balances(student, through=end)
    if request.GET.get("format") == "pdf":
        return pdf_document(
            "Student account statement",
            school_snapshot(config()),
            ["Date", "Event", "Account", "Debit", "Credit", "Owed", "Advance", "Deposit"],
            [
                [
                    r[k]
                    for k in (
                        "date",
                        "source",
                        "account",
                        "debit",
                        "credit",
                        "owed",
                        "advance",
                        "deposit",
                    )
                ]
                for r in data["rows"]
            ],
            identity=[("Student", student), ("Admission", student.admission_number)],
            filename="student-statement.pdf",
        )
    return page(
        request,
        "student.html",
        student=student,
        balances=balances,
        statement=data,
        form=date_form,
        invoices=invoices_visible_to(request.user).filter(student=student),
        payments=payments_visible_to(request.user).filter(student=student),
        credits=student.credit_lots.all() if capable(request.user, "allocate_credit") else [],
    )


@login_required
def invoice_list(request):
    require(request.user, "access_finance", staff=False)
    rows = invoices_visible_to(request.user)
    if query := request.GET.get("q", "").strip():
        rows = rows.filter(
            Q(number__icontains=query)
            | Q(student__admission_number__icontains=query)
            | Q(student__first_name__icontains=query)
            | Q(student__last_name__icontains=query)
        )
    if state := request.GET.get("state"):
        rows = rows.filter(state=state)
    return page(
        request,
        "invoices.html",
        records=paginate(
            request, rows.order_by("number" if request.GET.get("sort") == "number" else "-issue_on")
        ),
    )


@login_required
def invoice_detail(request, pk):
    invoice = get_object_or_404(invoices_visible_to(request.user), pk=pk)
    totals = invoice_totals(invoice)
    if request.GET.get("format") == "pdf":
        if invoice.state not in ("issued", "voided"):
            raise Http404
        event(request.user, "invoice_download", invoice.pk, student=invoice.student)
        data = invoice.snapshot
        return pdf_document(
            "Fee invoice",
            data["school"],
            ["Description", "Gross", "Discount", "Net"],
            [[r[k] for k in ("description", "gross", "discount", "net")] for r in data["lines"]]
            + [
                ["Current adjustments", "", "", totals["adjustments"]],
                ["Current outstanding", "", "", totals["balance"]],
            ],
            identity=[
                ("Invoice", invoice.number),
                ("Student", data["student"]),
                ("Admission", data["admission"]),
                ("Class / section", data["class"] + " / " + data["section"]),
                ("Issue / due", data["issue_on"] + " / " + data["due_on"]),
                ("Currency", invoice.currency),
            ],
            status=totals["status"].upper(),
            filename="fee-invoice.pdf",
        )
    return page(
        request,
        "invoice.html",
        invoice=invoice,
        totals=totals,
        lines=invoice.lines.all(),
        adjustments=invoice.adjustments.all(),
    )


@login_required
@require_POST
def invoice_action(request, pk):
    require(request.user, "generate_invoices")
    invoice = get_object_or_404(m.Invoice, pk=pk)
    try:
        action = request.POST.get("action")
        if action == "issue":
            issue_invoice(request.user, invoice.pk)
        elif action == "approval":
            request_action(
                request.user,
                "issue_invoice",
                invoice=invoice,
                day=invoice.issue_on,
                reason="Please independently review this invoice before issue",
            )
        elif action == "fine":
            apply_late_fee(request.user, invoice.pk)
        else:
            raise ValidationError("Choose a valid invoice action.")
    except (ValidationError, IntegrityError) as exc:
        messages.error(
            request,
            "; ".join(exc.messages)
            if isinstance(exc, ValidationError)
            else "A conflicting action was recorded; reload and review.",
        )
    else:
        messages.success(request, "Invoice action recorded successfully.")
    return redirect("finance:invoice", pk=invoice.pk)


@login_required
def bulk_billing(request):
    require(request.user, "generate_invoices")
    form = forms.BillingForm(request.POST or None)
    preview = None
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            if not data["students"].exists():
                if not data["school_class"]:
                    raise ValidationError(
                        "Select students or choose a class for this billing cycle."
                    )
                data["students"] = (
                    students_visible_to(request.user)
                    .filter(
                        enrollments__academic_year=data["cycle"].academic_year,
                        enrollments__section__school_class=data["school_class"],
                    )
                    .distinct()
                )
            if data["students"].count() > 200:
                raise ValidationError("Choose at most 200 students per batch.")
            cycle = data["cycle"]
            context = BillingContext(cycle, data["students"])
            preview = []
            for student in data["students"]:
                try:
                    rows = calculate_charges(student, cycle, config(), context)
                    preview.append(
                        {
                            "student": student,
                            "lines": rows,
                            "total": sum((r["gross"] - r["discount"] for r in rows), 0),
                            "error": "",
                        }
                    )
                except ValidationError as exc:
                    preview.append({"student": student, "error": "; ".join(exc.messages)})
            digest = fingerprint(
                {
                    "cycle": str(cycle.pk),
                    "students": sorted(str(p.pk) for p in data["students"]),
                    "preview": [
                        {
                            "student": str(row["student"].pk),
                            "total": str(row.get("total", "")),
                            "error": row["error"],
                            "lines": [
                                {
                                    "category": str(line["category"].pk),
                                    "structure": str(line["structure"].pk),
                                    "enrollment": line["enrollment"].pk,
                                    "gross": str(line["gross"]),
                                    "discount": str(line["discount"]),
                                }
                                for line in row.get("lines", [])
                            ],
                        }
                        for row in preview
                    ],
                }
            )
            if data["confirm"] and (
                not data["preview_token"]
                or request.session.get("finance_billing_preview") != [data["preview_token"], digest]
            ):
                raise ValidationError(
                    "Preview the exact batch first. Prices or selections may have changed."
                )
            if data["confirm"]:
                request.session.pop("finance_billing_preview", None)
                outcome = generate_invoices(request.user, cycle.pk, data["students"])
                messages.success(
                    request,
                    f"Generated {len(outcome['generated'])}; "
                    f"skipped {len(outcome['skipped'])}; failed {len(outcome['failed'])}.",
                )
                for failure in outcome["failed"]:
                    messages.error(request, f"{failure['student']}: {'; '.join(failure['errors'])}")
                return redirect("finance:invoices")
            import uuid

            token = str(uuid.uuid4())
            request.session["finance_billing_preview"] = [token, digest]
            form.data = form.data.copy()
            form.data["preview_token"] = token
        except ValidationError as exc:
            form_errors(form, exc)
    return form_page(request, "Bulk billing: preview and confirm", form, preview=preview)


@login_required
def collect(request):
    require(request.user, "collect_payments")
    form = forms.PaymentForm(request.POST or None, initial={"student": request.GET.get("student")})
    if request.method == "POST" and form.is_valid():
        data = dict(form.cleaned_data)
        intents = []
        for suffix in ("", "_2"):
            invoice = data.pop("invoice" + suffix)
            value = data.pop("allocated_amount" + suffix)
            if invoice:
                intents.append({"invoice": invoice.pk, "amount": value})
        try:
            payment = collect_payment(request.user, **data, allocations=intents)
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(
                request,
                "Payment posted and receipt created."
                if payment.state == "posted"
                else "Payment is awaiting independent approval; no money has been posted.",
            )
            return redirect("finance:receipt", pk=payment.pk)
    return form_page(request, "Record a manual payment", form)


@login_required
def receipts(request):
    require(request.user, "access_finance", staff=False)
    rows = payments_visible_to(request.user)
    if query := request.GET.get("q", "").strip():
        rows = rows.filter(
            Q(number__icontains=query)
            | Q(reference__icontains=query)
            | Q(student__admission_number__icontains=query)
        )
    return page(request, "receipts.html", records=paginate(request, rows))


@login_required
def receipt(request, pk):
    payment = get_object_or_404(payments_visible_to(request.user), pk=pk)
    reversal = reversal_for(payment)
    status = (
        "REVERSED - ORIGINAL RECEIPT RETAINED" if reversal else payment.get_state_display().upper()
    )
    if request.GET.get("format") == "pdf":
        if payment.state != "posted":
            raise Http404
        data = payment.snapshot
        event(request.user, "receipt_download", payment.pk, student=payment.student)
        return pdf_document(
            "Payment receipt",
            data["school"],
            ["Invoice", "Allocated", "Balance at receipt"],
            [[r["invoice"], r["amount"], r["balance"]] for r in data["allocations"]],
            identity=[
                ("Receipt", payment.number),
                ("Student", data["student"]),
                ("Admission", data["admission"]),
                ("Class / section", data["class"] + " / " + data["section"]),
                ("Received", data["amount"] + " " + data["school"]["currency"]),
                ("Method / reference", data["method"] + " / " + data["reference"]),
                ("Paid on", data["paid_on"]),
                ("Issued at", data["issued_at"]),
                ("Cashier", data["cashier"]),
                ("Balance owed at issue", data["balances"]["owed"]),
                ("Advance at issue", data["balances"]["advance"]),
            ],
            status=status,
            filename="payment-receipt.pdf",
        )
    return page(
        request,
        "receipt.html",
        payment=payment,
        data=payment.snapshot,
        status=status,
        reversal=reversal,
    )


@login_required
def allocate(request):
    require(request.user, "allocate_credit")
    form = forms.AllocationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            allocate_credit(
                request.user,
                data["credit"].pk,
                data["invoice"].pk,
                data["value"],
                data["day"],
                idempotency_key=data["idempotency_key"],
            )
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(request, "Allocation recorded or submitted for required approval.")
            return redirect("finance:student", pk=data["credit"].student_id)
    return form_page(request, "Allocate existing student advance credit", form)


@login_required
def requests(request):
    require(request.user, "view_all_finance")
    rows = m.FinancialRequest.objects.select_related("student", "requested_by", "reviewed_by")
    if state := request.GET.get("state"):
        rows = rows.filter(state=state)
    if kind := request.GET.get("kind"):
        rows = rows.filter(kind=kind)
    return page(request, "requests.html", records=paginate(request, rows))


@login_required
def action_request(request):
    require(request.user, "view_all_finance")
    # Action-specific service permissions are checked again after validation.
    form = forms.ActionForm(
        request.POST or None,
        initial={"kind": request.GET.get("kind"), "invoice": request.GET.get("invoice")},
    )
    if request.method == "POST" and form.is_valid():
        data = dict(form.cleaned_data)
        kind = data.pop("kind")
        payload = {}
        for field in ("concession_type", "category", "starts_on", "ends_on", "financial_year"):
            value = data.pop(field)
            if value:
                payload["year" if field == "financial_year" else field] = (
                    str(value.pk) if hasattr(value, "pk") else value.isoformat()
                )
        if kind == "opening_student":
            payload["mode"] = "advance"
        if kind == "allocate":
            import uuid

            payload["key"] = str(uuid.uuid4())
        data = {k: v for k, v in data.items() if v is not None}
        try:
            item = request_action(request.user, kind, payload=payload, **data)
        except (ValidationError, IntegrityError, ValueError, KeyError) as exc:
            form_errors(
                form,
                exc
                if isinstance(exc, (ValidationError, IntegrityError))
                else ValidationError("Complete the source document and required action details."),
            )
        else:
            messages.success(
                request, "Request submitted. An independent authorized reviewer must decide it."
            )
            return redirect("finance:request", pk=item.pk)
    return form_page(request, "Request a financial action", form)


@login_required
def request_detail(request, pk):
    require(request.user, "view_all_finance")
    item = get_object_or_404(
        m.FinancialRequest.objects.select_related(
            "student", "invoice", "payment", "requested_by", "reviewed_by"
        ),
        pk=pk,
    )
    form = forms.DecisionForm(request.POST or None)
    if request.method == "POST":
        require(request.user, "approve_finance")
        if form.is_valid():
            try:
                decide_request(
                    request.user,
                    item.pk,
                    approve=form.cleaned_data["approve"],
                    reason=form.cleaned_data["reason"],
                )
            except (ValidationError, IntegrityError) as exc:
                form_errors(form, exc)
            else:
                messages.success(
                    request,
                    "Independent decision recorded and the approved action executed atomically.",
                )
                return redirect("finance:request", pk=item.pk)
    return page(request, "request.html", item=item, form=form)


@login_required
def expenses(request):
    require(request.user, "record_expenses")
    return page(
        request,
        "expenses.html",
        records=paginate(
            request,
            m.Expense.objects.select_related("category", "request").order_by("-occurred_on"),
        ),
    )


@login_required
def expense_create(request):
    require(request.user, "record_expenses")
    form = forms.ExpenseForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            request_expense(request.user, **form.cleaned_data)
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(request, "Expense submitted for independent approval.")
            return redirect("finance:expenses")
    return form_page(request, "Request an operational expense", form)


@login_required
def expense_pay(request, pk):
    require(request.user, "record_expenses")
    expense = get_object_or_404(m.Expense, pk=pk)
    form = forms.ExpensePaymentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            pay_expense(request.user, expense.pk, **form.cleaned_data)
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            messages.success(request, "Approved expense payment posted.")
            return redirect("finance:expenses")
    return form_page(request, f"Pay expense: {expense.payee}", form)


@login_required
def attachment(request, pk):
    require(request.user, "record_expenses")
    expense = get_object_or_404(m.Expense, pk=pk)
    if not expense.attachment:
        raise Http404
    try:
        response = FileResponse(expense.attachment.open("rb"), content_type="image/png")
    except OSError as exc:
        raise Http404 from exc
    response["Cache-Control"] = "private, no-store"
    response["Content-Disposition"] = 'inline; filename="expense-scan.png"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
def reconcile(request):
    require(request.user, "reconcile_accounts")
    form = forms.ReconciliationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = dict(form.cleaned_data)
        account, reason = data.pop("account"), data.pop("reason")
        data["lines"] = [row.pk for row in data["lines"]]
        data["starts_on"] = data["starts_on"].isoformat()
        data["ends_on"] = data["ends_on"].isoformat()
        try:
            item = request_reconciliation(request.user, account, data, reason)
        except (ValidationError, IntegrityError) as exc:
            form_errors(form, exc)
        else:
            return redirect("finance:request", pk=item.pk)
    return form_page(request, "Reconcile a manual cash / bank statement", form)


@login_required
def reports(request):
    require(request.user, "view_finance_reports")
    form = forms.ReportForm(request.GET)
    data = None
    if form.is_valid():
        try:
            data = financial_report(request.user, **form.cleaned_data)
        except ValidationError as exc:
            form_errors(form, exc)
    if data and request.GET.get("format") in ("csv", "pdf"):
        headers = [
            "Invoice",
            "Admission",
            "Student",
            "Due",
            "Effective total",
            "Allocated",
            "Outstanding",
            "Status",
        ]
        rows = [
            [
                r["invoice"].number,
                r["invoice"].student.admission_number,
                str(r["invoice"].student),
                r["invoice"].due_on,
                r["effective"],
                r["allocated"],
                r["balance"],
                r["status"],
            ]
            for r in data["invoices"]
        ]
        register = request.GET.get("register", "invoices")
        if register == "receipts":
            headers = [
                "Receipt",
                "Admission",
                "Student",
                "Date",
                "Method",
                "Reference",
                "Cashier",
                "Amount",
                "Status",
            ]
            rows = [
                [
                    r["payment"].number,
                    r["payment"].student.admission_number,
                    str(r["payment"].student),
                    r["payment"].paid_on,
                    r["payment"].method.name,
                    r["payment"].reference,
                    r["payment"].created_by.display_name,
                    r["payment"].amount,
                    r["status"],
                ]
                for r in data["payment_register"]
            ]
        elif register == "expenses":
            headers = ["Date", "Payee", "Category", "Description", "Amount", "Payment"]
            rows = [
                [
                    r.occurred_on,
                    r.payee,
                    r.category.name,
                    r.description,
                    r.amount,
                    "paid" if hasattr(r, "payment") else "unpaid",
                ]
                for r in data["expense_register"]
            ]
        elif register == "trial":
            headers = ["Code", "Account", "Kind", "Debit", "Credit"]
            rows = [
                [
                    r[k]
                    for k in ("account__code", "account__name", "account__kind", "debit", "credit")
                ]
                for r in data["trial_balance"]
            ]
        elif register == "collections":
            headers = ["Grouping", "Value", "Collected, reversed receipts excluded"]
            rows = [
                [kind, k, v]
                for kind in ("daily", "methods", "cashiers")
                for k, v in data[kind].items()
            ]
        event(request.user, "finance_report_export", register)
        if request.GET["format"] == "pdf":
            return pdf_document(
                "School financial register",
                school_snapshot(config()),
                headers,
                rows,
                filename="finance-register.pdf",
            )
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="finance-register.csv"'
        response["Cache-Control"] = "private, no-store"
        writer = csv.writer(response)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(
                [
                    "'" + str(v)
                    if str(v).lstrip().startswith(("=", "+", "-", "@", "\t", "\r"))
                    else v
                    for v in row
                ]
            )
        return response
    return page(request, "reports.html", form=form, report=data)


@login_required
def journal(request):
    require(request.user, "view_journal")
    rows = (
        m.JournalEntry.objects.select_related("actor", "period")
        .prefetch_related("lines__account", "lines__student")
        .order_by("-occurred_on", "-created_at")
    )
    return page(request, "journal.html", records=paginate(request, rows))


@login_required
def notices(request):
    require(request.user, "access_finance", staff=False)
    return page(
        request, "notices.html", records=paginate(request, notices_visible_to(request.user))
    )


@login_required
@require_POST
def reminders(request):
    count = send_reminders(request.user)
    messages.success(
        request, f"Reminder evaluation completed for {count} invoices. Delivery remains internal."
    )
    return redirect("finance:dashboard")
