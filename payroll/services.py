from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models, transaction
from django.utils import timezone

from audit.services import record_event
from finance.common import locked_config
from finance.ledger import _post

from .models import PayrollAction, PayrollRun, PayrollSettings, Payslip, PayslipLine, SalaryRevision


def require(actor, permission):
    if not actor.is_active or not actor.has_perm("payroll." + permission):
        raise PermissionDenied


def prorate(amount, employee, period):
    records = employee.employment_records.filter(starts_on__lte=period.ends_on).order_by(
        "-starts_on"
    )
    record = records.first()
    if not record or (record.ends_on and record.ends_on < period.starts_on):
        return Decimal("0")
    active_start = max(record.starts_on, period.starts_on)
    active_end = min(record.ends_on or period.ends_on, period.ends_on)
    total = (period.ends_on - period.starts_on).days + 1
    active = (active_end - active_start).days + 1
    return (amount * Decimal(active) / Decimal(total)).quantize(Decimal("0.01"))


@transaction.atomic
def generate(actor, period, employees):
    require(actor, "manage_payroll")
    run, created = PayrollRun.objects.select_for_update().get_or_create(
        period=period, defaults={"prepared_by": actor}
    )
    if not created and run.state != "draft":
        raise ValidationError("This payroll period is already in review or finalized.")
    for employee in employees:
        slip, new = Payslip.objects.get_or_create(
            run=run, employee=employee, defaults={"reference": f"PAY-{period.pk}-{employee.pk}"}
        )
        if not new:
            continue
        revisions = (
            SalaryRevision.objects.filter(employee=employee, effective_from__lte=period.ends_on)
            .filter(
                models.Q(effective_to__isnull=True) | models.Q(effective_to__gte=period.starts_on)
            )
            .select_related("component")
        )
        earnings = deductions = Decimal("0")
        snapshots = []
        for revision in revisions:
            value = prorate(revision.amount, employee, period)
            PayslipLine.objects.create(
                payslip=slip,
                component=revision.component,
                name=revision.component.name,
                kind=revision.component.kind,
                amount=value,
            )
            snapshots.append(
                {
                    "code": revision.component.code,
                    "name": revision.component.name,
                    "kind": revision.component.kind,
                    "amount": str(value),
                }
            )
            if revision.component.kind in ("earning", "reimbursement"):
                earnings += value
            else:
                deductions += value
        if deductions > earnings:
            raise ValidationError("Payroll deductions cannot exceed gross pay.")
        slip.gross, slip.deductions, slip.net, slip.snapshot = (
            earnings,
            deductions,
            earnings - deductions,
            {"components": snapshots, "period": period.name},
        )
        slip.save()
    record_event("payroll.generated", actor=actor, target=run.pk)
    return run


@transaction.atomic
def transition(actor, run_id, action, reason=""):
    run = PayrollRun.objects.select_for_update().select_related("period").get(pk=run_id)
    if action == "submit":
        require(actor, "manage_payroll")
        target = "submitted"
    elif action == "approve":
        require(actor, "approve_payroll")
        if actor.pk == run.prepared_by_id:
            raise ValidationError("Payroll requires an independent approver.")
        target, run.reviewed_by = "approved", actor
    elif action == "finalize":
        require(actor, "manage_payroll")
        if run.state != "approved":
            raise ValidationError("Approve payroll before finalization.")
        config = PayrollSettings.objects.select_related("salary_payable_account").get()
        finance_settings = locked_config()
        lines = []
        for slip in run.payslips.select_related("employee"):
            for line in slip.lines.select_related("component__account"):
                if line.kind in ("earning", "reimbursement"):
                    lines.append((line.component.account, None, line.amount, 0))
                else:
                    lines.append((line.component.account, None, 0, line.amount))
            lines.append((config.salary_payable_account, None, 0, slip.net))
        journal = _post(
            actor,
            finance_settings,
            source_key=f"payroll:{run.pk}",
            source_type="payroll",
            source_id=run.pk,
            day=run.period.payment_date,
            memo=f"Payroll {run.period.name}",
            lines=lines,
        )
        for slip in run.payslips.all():
            slip.journal, slip.state = journal, "released"
            slip.save(update_fields=["journal", "state", "updated_at"])
            from communications.notices import add

            add(
                slip.employee.user_id,
                f"payroll:{slip.pk}:released",
                f"Payslip released: {run.period.name}",
                f"/payroll/payslips/{slip.pk}/",
                category_name="payroll",
            )
        target = "finalized"
    else:
        raise ValidationError("Invalid payroll action.")
    expected = {"submit": "draft", "approve": "submitted", "finalize": "approved"}[action]
    if run.state != expected:
        raise ValidationError("Invalid payroll transition.")
    run.state = target
    run.save()
    PayrollAction.objects.create(run=run, actor=actor, action=action, reason=reason)
    record_event("payroll." + action, actor=actor, target=run.pk)
    return run


@transaction.atomic
def record_payment(actor, payslip_id):
    require(actor, "pay_payroll")
    slip = (
        Payslip.objects.select_for_update()
        .select_related("run__period", "employee")
        .get(pk=payslip_id)
    )
    if slip.state != "released" or slip.payment_journal_id:
        raise ValidationError("Only one payment may be recorded for a released payslip.")
    config = PayrollSettings.objects.select_related(
        "salary_payable_account", "payment_account"
    ).get()
    journal = _post(
        actor,
        locked_config(),
        source_key=f"payroll-payment:{slip.pk}",
        source_type="payroll_payment",
        source_id=slip.pk,
        day=slip.run.period.payment_date,
        memo=f"Payroll payment {slip.reference}",
        lines=[
            (config.salary_payable_account, None, slip.net, 0),
            (config.payment_account, None, 0, slip.net),
        ],
    )
    slip.payment_journal = journal
    slip.paid_at = timezone.now()
    slip.state = "paid"
    slip.save()
    record_event("payroll.paid", actor=actor, target=slip.pk)
    return slip


@transaction.atomic
def reverse(actor, run_id, reason, *, day=None):
    """Reverse an unpaid finalized run with a compensating finance journal."""
    require(actor, "approve_payroll")
    run = (
        PayrollRun.objects.select_for_update()
        .select_related("period", "prepared_by")
        .get(pk=run_id)
    )
    if run.state != "finalized" or run.reversal_journal_id or not reason.strip():
        raise ValidationError("A finalized payroll and a reversal reason are required.")
    if run.payslips.exclude(state="released").exists():
        raise ValidationError("Paid or previously reversed payroll cannot be reversed as a run.")
    journal = run.payslips.exclude(journal=None).values_list("journal", flat=True).first()
    source = run.payslips.first().journal if journal else None
    if not source:
        raise ValidationError("The payroll has no posted accrual to reverse.")
    reversal = _post(
        actor,
        locked_config(),
        source_key=f"payroll-reversal:{run.pk}",
        source_type="payroll_reversal",
        source_id=run.pk,
        day=day or timezone.localdate(),
        memo=f"Payroll reversal {run.period.name}: {reason}",
        lines=[
            (line.account, line.student, line.credit, line.debit)
            for line in source.lines.select_related("account", "student")
        ],
        reversal_of=source,
    )
    run.state, run.reason = "reversed", reason
    run.reversal_journal, run.reversed_at = reversal, timezone.now()
    run.save()
    run.payslips.update(state="reversed", updated_at=timezone.now())
    PayrollAction.objects.create(run=run, actor=actor, action="reverse", reason=reason)
    record_event("payroll.reversed", actor=actor, target=run.pk)
    return run
