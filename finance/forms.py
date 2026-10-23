import uuid

from django import forms
from django.forms import modelform_factory

from academics.models import AcademicYear, SchoolClass
from core.form_mixins import StyledFormMixin
from people.models import Student

from . import models as m
from .common import school_day


class SetupForm(StyledFormMixin, forms.ModelForm):
    pass


SETUP = {
    "settings": (m.FinanceSettings, "Finance settings", "manage_finance"),
    "accounts": (m.Account, "Cash, bank and ledger accounts", "manage_finance"),
    "years": (m.FinancialYear, "Financial years", "manage_finance"),
    "periods": (m.FinancialPeriod, "Financial periods", "manage_finance"),
    "methods": (m.PaymentMethod, "Manual payment methods", "manage_finance"),
    "categories": (m.FeeCategory, "Fee categories", "manage_fees"),
    "structures": (m.FeeStructure, "Fee structures and revisions", "manage_fees"),
    "lines": (m.FeeLine, "Structure charges", "manage_fees"),
    "assignments": (m.FeeAssignment, "Student fee assignments", "manage_fees"),
    "concessions": (m.ConcessionType, "Scholarships and concessions", "manage_fees"),
    "cycles": (m.BillingCycle, "Scheduled billing periods", "manage_fees"),
    "expense-categories": (m.ExpenseCategory, "Expense categories", "manage_finance"),
}


def setup_form(kind):
    return modelform_factory(
        SETUP[kind][0], form=SetupForm, exclude=["is_closed", "created_at", "updated_at"]
    )


class BillingForm(StyledFormMixin, forms.Form):
    cycle = forms.ModelChoiceField(queryset=m.BillingCycle.objects.all())
    students = forms.ModelMultipleChoiceField(
        queryset=Student.objects.all(),
        required=False,
        help_text="Select students, or leave blank and choose a class. Maximum 200 per batch.",
    )
    school_class = forms.ModelChoiceField(queryset=SchoolClass.objects.all(), required=False)
    preview_token = forms.CharField(required=False, widget=forms.HiddenInput)
    confirm = forms.BooleanField(required=False, label="Confirm this reviewed billing batch")


class PaymentForm(StyledFormMixin, forms.Form):
    student = forms.ModelChoiceField(queryset=Student.objects.all())
    value = forms.DecimalField(
        max_digits=18, decimal_places=3, min_value=0.001, label="Amount received"
    )
    day = forms.DateField(initial=school_day)
    method = forms.ModelChoiceField(queryset=m.PaymentMethod.objects.filter(is_active=True))
    reference = forms.CharField(
        max_length=100,
        help_text=(
            "Unique manual slip reference. Never enter a card number, CVV, PIN or credentials."
        ),
    )
    invoice = forms.ModelChoiceField(
        queryset=m.Invoice.objects.filter(state="issued"), required=False
    )
    allocated_amount = forms.DecimalField(
        max_digits=18,
        decimal_places=3,
        required=False,
        help_text="Leave blank to hold the full amount as advance credit.",
    )
    invoice_2 = forms.ModelChoiceField(
        queryset=m.Invoice.objects.filter(state="issued"),
        required=False,
        label="Second invoice (optional)",
    )
    allocated_amount_2 = forms.DecimalField(max_digits=18, decimal_places=3, required=False)
    notes = forms.CharField(max_length=300, required=False)
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)

    def clean(self):
        data = super().clean()
        for suffix in ("", "_2"):
            invoice = data.get("invoice" + suffix)
            value = data.get("allocated_amount" + suffix)
            if bool(invoice) != bool(value):
                self.add_error(
                    "allocated_amount" + suffix,
                    "Choose both an invoice and a positive allocation, or leave both blank.",
                )
            if invoice and data.get("student") and invoice.student_id != data["student"].pk:
                self.add_error(
                    "invoice" + suffix, "Choose an invoice belonging to the selected student."
                )
        return data


class ActionForm(StyledFormMixin, forms.Form):
    kind = forms.ChoiceField(choices=m.REQUEST_KINDS)
    student = forms.ModelChoiceField(queryset=Student.objects.all(), required=False)
    invoice = forms.ModelChoiceField(queryset=m.Invoice.objects.all(), required=False)
    payment = forms.ModelChoiceField(
        queryset=m.Payment.objects.filter(state="posted"), required=False
    )
    credit = forms.ModelChoiceField(queryset=m.CreditLot.objects.all(), required=False)
    allocation = forms.ModelChoiceField(queryset=m.Allocation.objects.all(), required=False)
    line = forms.ModelChoiceField(queryset=m.InvoiceLine.objects.all(), required=False)
    charge = forms.ModelChoiceField(
        queryset=m.InvoiceAdjustment.objects.filter(amount__gt=0), required=False
    )
    period = forms.ModelChoiceField(queryset=m.FinancialPeriod.objects.all(), required=False)
    source_account = forms.ModelChoiceField(
        queryset=m.Account.objects.filter(control__in=["cash", "bank"], is_active=True),
        required=False,
    )
    target_account = forms.ModelChoiceField(
        queryset=m.Account.objects.filter(control__in=["cash", "bank"], is_active=True),
        required=False,
    )
    amount_value = forms.DecimalField(
        max_digits=18,
        decimal_places=3,
        initial=0,
        min_value=0,
        required=False,
        label="Amount / concession value",
    )
    day = forms.DateField(initial=school_day)
    reason = forms.CharField(
        min_length=8, max_length=1000, widget=forms.Textarea(attrs={"rows": 3})
    )
    concession_type = forms.ModelChoiceField(
        queryset=m.ConcessionType.objects.filter(is_active=True), required=False
    )
    category = forms.ModelChoiceField(queryset=m.FeeCategory.objects.all(), required=False)
    starts_on = forms.DateField(required=False)
    ends_on = forms.DateField(required=False)
    financial_year = forms.ModelChoiceField(queryset=m.FinancialYear.objects.all(), required=False)

    def clean(self):
        data = super().clean()
        if data.get("kind") == "exempt_fines":
            for name in ("student", "starts_on", "ends_on"):
                if not data.get(name):
                    self.add_error(name, "Required for a dated late-fee exemption.")
        if data.get("kind") == "discount":
            for name in ("concession_type", "starts_on", "ends_on", "student"):
                if not data.get(name):
                    self.add_error(name, "Required for a concession request.")
        if data.get("kind") in ("close_year", "reopen_year") and not data.get("financial_year"):
            self.add_error("financial_year", "Select the financial year.")
        if data.get("kind") in ("expense", "payment", "reconcile"):
            self.add_error(
                "kind", "Use the dedicated expense, collection or reconciliation screen."
            )
        return data


class DecisionForm(StyledFormMixin, forms.Form):
    approve = forms.TypedChoiceField(
        choices=[("yes", "Approve and execute"), ("no", "Reject")], coerce=lambda v: v == "yes"
    )
    reason = forms.CharField(
        min_length=8, max_length=1000, widget=forms.Textarea(attrs={"rows": 3})
    )


class ExpenseForm(StyledFormMixin, forms.Form):
    category = forms.ModelChoiceField(queryset=m.ExpenseCategory.objects.all())
    day = forms.DateField(initial=school_day)
    payee = forms.CharField(max_length=140)
    value = forms.DecimalField(max_digits=18, decimal_places=3)
    description = forms.CharField(
        min_length=8, max_length=500, widget=forms.Textarea(attrs={"rows": 3})
    )
    attachment = forms.FileField(
        required=False,
        help_text="Optional private PNG/JPEG scan, maximum 2 MB. Metadata is removed.",
    )


class ExpensePaymentForm(StyledFormMixin, forms.Form):
    account = forms.ModelChoiceField(
        queryset=m.Account.objects.filter(control__in=["cash", "bank"], is_active=True)
    )
    day = forms.DateField(initial=school_day)
    reference = forms.CharField(max_length=100)


class AllocationForm(StyledFormMixin, forms.Form):
    credit = forms.ModelChoiceField(queryset=m.CreditLot.objects.all())
    invoice = forms.ModelChoiceField(queryset=m.Invoice.objects.filter(state="issued"))
    value = forms.DecimalField(max_digits=18, decimal_places=3)
    day = forms.DateField(initial=school_day)
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)


class ReconciliationForm(StyledFormMixin, forms.Form):
    account = forms.ModelChoiceField(
        queryset=m.Account.objects.filter(control__in=["cash", "bank"], is_active=True)
    )
    starts_on = forms.DateField()
    ends_on = forms.DateField()
    opening = forms.DecimalField(max_digits=18, decimal_places=3)
    closing = forms.DecimalField(max_digits=18, decimal_places=3)
    lines = forms.ModelMultipleChoiceField(
        queryset=m.JournalLine.objects.filter(
            account__control__in=["cash", "bank"], journal__state="posted"
        ).exclude(reconciliation_links__is_active=True),
        required=False,
    )
    reason = forms.CharField(min_length=8, max_length=1000)


class ReportForm(StyledFormMixin, forms.Form):
    start = forms.DateField(required=False)
    end = forms.DateField(required=False)
    year = forms.ModelChoiceField(queryset=AcademicYear.objects.all(), required=False)
    school_class = forms.ModelChoiceField(queryset=SchoolClass.objects.all(), required=False)
    overdue = forms.BooleanField(required=False)

    def clean(self):
        data = super().clean()
        if data.get("start") and data.get("end") and data["start"] > data["end"]:
            self.add_error("end", "The end date must follow the start date.")
        return data
