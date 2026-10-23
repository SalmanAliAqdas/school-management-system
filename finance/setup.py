from django.core.exceptions import ValidationError
from django.db import transaction

from .common import CONTROL_KINDS, amount, event, locked_config, require, validate_number_format
from .models import (
    Account,
    BillingCycle,
    ConcessionType,
    FeeAssignment,
    FeeCategory,
    FeeLine,
    FeeStructure,
    FinanceSettings,
    FinancialPeriod,
    FinancialYear,
    Invoice,
    InvoiceLine,
    Payment,
    PaymentMethod,
)


@transaction.atomic
def save_setup(actor, instance):
    financial = isinstance(
        instance, (FinanceSettings, Account, FinancialYear, FinancialPeriod, PaymentMethod)
    )
    require(actor, "manage_finance" if financial else "manage_fees")
    settings = locked_config()
    original = type(instance).objects.filter(pk=instance.pk).first() if instance.pk else None
    used = Invoice.objects.exists() or Payment.objects.exists() or FeeLine.objects.exists()
    if isinstance(instance, FinanceSettings):
        if (
            original
            and used
            and any(
                getattr(original, f) != getattr(instance, f) for f in ("currency", "decimal_places")
            )
        ):
            raise ValidationError(
                "Currency and precision are frozen once priced financial records exist."
            )
        from core.models import SchoolSettings

        school = SchoolSettings.objects.first()
        if school and instance.currency != school.currency:
            raise ValidationError(
                "Finance currency must match the school's configured base currency."
            )
        if (
            not len(instance.currency) == 3
            or not instance.currency.isalpha()
            or not instance.currency.isupper()
        ):
            raise ValidationError("Use an uppercase three-letter currency code.")
        validate_number_format(instance.invoice_format)
        validate_number_format(instance.receipt_format)
        if instance.fine_mode == "percent" and instance.fine_value > 100:
            raise ValidationError("Fine percentage must be at most 100.")
    if isinstance(instance, Account):
        if instance.kind != CONTROL_KINDS[instance.control]:
            raise ValidationError("The account type must match its accounting control role.")
        if (
            original
            and original.journal_lines.exists()
            and any(
                getattr(instance, f) != getattr(original, f) for f in ("code", "kind", "control")
            )
        ):
            raise ValidationError("Used account identities and control roles cannot be changed.")
    if isinstance(instance, (FinancialYear, FinancialPeriod)) and original:
        if instance.is_closed != original.is_closed:
            raise ValidationError("Use independent financial closing/reopening controls.")
        journals = (
            original.journals.exists()
            if isinstance(instance, FinancialPeriod)
            else original.periods.filter(journals__isnull=False).exists()
        )
        if journals:
            raise ValidationError(
                "A financial period/year with postings has a protected definition."
            )
    if isinstance(instance, FinancialPeriod):
        if (
            not instance.financial_year.starts_on
            <= instance.starts_on
            <= instance.ends_on
            <= instance.financial_year.ends_on
        ):
            raise ValidationError("Financial period dates must fall inside the financial year.")
        if instance.financial_year.is_closed:
            raise ValidationError("Choose an open financial year.")
    if isinstance(instance, PaymentMethod):
        if instance.account.control not in ("cash", "bank") or not instance.account.is_active:
            raise ValidationError("Manual payment methods require an active cash/bank account.")
        if (
            original
            and original.payment_set.exists()
            and original.account_id != instance.account_id
        ):
            raise ValidationError("A used payment method's accounting account is protected.")
    if isinstance(instance, FeeCategory):
        valid = "equity" if instance.treatment == "opening" else "revenue"
        if instance.income_account.control != valid or not instance.income_account.is_active:
            raise ValidationError(
                "Choose an active revenue account, or equity for an opening category."
            )
        if instance.treatment == "deposit" and (
            not instance.refundable or instance.late_fee_eligible
        ):
            raise ValidationError("Deposits must be refundable and ineligible for late fees.")
        if instance.treatment == "opening":
            require(actor, "manage_finance")
        if original and original.invoiceline_set.exists():
            changed = [
                f.attname
                for f in instance._meta.concrete_fields
                if f.name not in ("updated_at", "is_active")
                and getattr(original, f.attname) != getattr(instance, f.attname)
            ]
            if changed:
                raise ValidationError(
                    "Used fee category definitions are protected; create another category."
                )
    if isinstance(instance, FeeStructure):
        if (
            instance.academic_year.status != "open"
            or not instance.academic_year.starts_on
            <= instance.starts_on
            <= instance.ends_on
            <= instance.academic_year.ends_on
        ):
            raise ValidationError("Choose effective dates inside an open academic year.")
        if instance.section_id and instance.section.school_class_id != instance.school_class_id:
            raise ValidationError("The section must belong to the configured class.")
        if original and InvoiceLine.objects.filter(fee_line__structure=original).exists():
            raise ValidationError("Used fee structures are immutable. Create a future revision.")
        if instance.revises_id and not original:
            previous = instance.revises
            if instance.starts_on <= previous.starts_on or any(
                getattr(instance, f) != getattr(previous, f)
                for f in (
                    "academic_year_id",
                    "school_class_id",
                    "section_id",
                    "frequency",
                    "assignment_only",
                )
            ):
                raise ValidationError(
                    "A revision must start later and keep its year, class, section, "
                    "frequency and assignment scope."
                )
            instance.family = previous.family
            instance.revision = previous.revision + 1
    if isinstance(instance, FeeLine):
        if (
            original
            and original.invoiceline_set.exists()
            or InvoiceLine.objects.filter(fee_line__structure=instance.structure).exists()
        ):
            raise ValidationError("Used fee lines are protected; create a new structure revision.")
        instance.amount = amount(instance.amount, settings)
    if isinstance(instance, FeeAssignment):
        if original and original.invoiceline_set.exists():
            raise ValidationError("Used assignments are protected; create a new dated assignment.")
        if (
            not instance.structure.starts_on
            <= instance.starts_on
            <= instance.ends_on
            <= instance.structure.ends_on
        ):
            raise ValidationError("Assignment dates must fall inside the selected structure.")
        if instance.amount_override is not None:
            if (
                not instance.category_id
                or not instance.structure.lines.filter(category=instance.category).exists()
            ):
                raise ValidationError(
                    "Select the structure category receiving the amount override."
                )
            instance.amount_override = amount(instance.amount_override, settings, positive=False)
        overlaps = FeeAssignment.objects.filter(
            student=instance.student,
            category=instance.category,
            starts_on__lte=instance.ends_on,
            ends_on__gte=instance.starts_on,
        ).exclude(pk=instance.pk)
        if overlaps.exists():
            raise ValidationError(
                "This student has an overlapping assignment for that scope; use "
                "non-overlapping dates."
            )
    if isinstance(instance, ConcessionType):
        if original and original.concessionaward_set.exists():
            raise ValidationError(
                "Awarded concession definitions are protected; create a new type."
            )
        instance.default_value = amount(instance.default_value, settings)
        if instance.mode == "percent" and instance.default_value > 100:
            raise ValidationError("Concession percentages must not exceed 100.")
    if isinstance(instance, BillingCycle):
        if original and original.invoice_set.exists():
            raise ValidationError("Used billing cycles are protected.")
        if (
            instance.academic_year.status != "open"
            or not instance.academic_year.starts_on
            <= instance.starts_on
            <= instance.ends_on
            <= instance.academic_year.ends_on
        ):
            raise ValidationError("Billing periods must be inside an open academic year.")
        if (instance.ends_on - instance.starts_on).days > 365:
            raise ValidationError("A billing cycle supports at most 366 calendar days.")
    instance.full_clean()
    instance.save()
    event(actor, "setup_saved", f"{instance._meta.model_name}:{instance.pk}")
    return instance
