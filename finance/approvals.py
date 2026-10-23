"""Independent financial decisions and compensating transactions."""

from datetime import date

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum

from .common import ZERO, amount, control, event, locked_config, require, school_day, school_now
from .ledger import _post, period_for
from .models import (
    Account,
    ConcessionAward,
    ConcessionType,
    CreditLot,
    Expense,
    FinancialRequest,
    InvoiceAdjustment,
    JournalEntry,
    Payment,
    Refund,
    RevenueRecognition,
)
from .payments import (
    _allocate,
    _post_payment,
    _release,
    active_allocations,
    allocation_remaining,
    deposit_available,
    invoice_totals,
    lot_available,
    reversal_for,
)


def _cash(account):
    if not account or not account.is_active or account.control not in ("cash", "bank"):
        raise ValidationError("Choose an active cash or bank account.")


def _validate(kind, value, day, payload, refs, settings, *, request=None):
    if kind not in dict(FinancialRequest._meta.get_field("kind").choices):
        raise ValidationError("Unknown financial action.")
    if day > school_day():
        raise ValidationError("Future financial actions cannot be posted.")
    if kind not in ("discount", "reopen_period", "close_year", "reopen_year"):
        period_for(day)
    invoice = refs.get("invoice")
    line = refs.get("line")
    charge = refs.get("charge")
    credit = refs.get("credit")
    allocation = refs.get("allocation")
    payment = refs.get("payment")
    if invoice and kind not in ("issue_invoice", "replace") and invoice.state != "issued":
        raise ValidationError("Choose an issued invoice.")
    if line and (not invoice or line.invoice_id != invoice.pk):
        raise ValidationError("The selected line must belong to this invoice.")
    if charge and (not invoice or charge.invoice_id != invoice.pk or charge.amount <= 0):
        raise ValidationError("Choose an original positive charge on this invoice.")
    if invoice and day < invoice.issue_on:
        raise ValidationError("The action cannot precede its original invoice.")
    if kind == "issue_invoice":
        if not invoice or invoice.state not in ("draft", "approved"):
            raise ValidationError("Choose a draft invoice.")
    elif kind in ("credit", "writeoff", "refund_fee", "recognize"):
        if not line or not invoice:
            raise ValidationError("Select the original invoice and fee line.")
        credited = -(line.adjustments.aggregate(v=Sum("amount"))["v"] or ZERO)
        if value > line.net - credited:
            raise ValidationError("This adjustment exceeds the remaining original fee.")
        if kind == "writeoff" and line.details["treatment"] not in ("earned", "opening"):
            raise ValidationError(
                "Use a credit note for deferred fees or deposits. Write-offs are unsupported."
            )
        if kind == "refund_fee":
            if not line.details["refundable"] or line.details["treatment"] == "deposit":
                raise ValidationError("Only a refundable ordinary fee can use this workflow.")
            reserved = FinancialRequest.objects.filter(
                kind="refund_fee", line=line, state="pending"
            )
            if request:
                reserved = reserved.exclude(pk=request.pk)
            if value > active_allocations(line=line) - (
                reserved.aggregate(v=Sum("amount"))["v"] or ZERO
            ):
                raise ValidationError("Refund requests exceed the paid refundable amount.")
            _cash(refs.get("target_account"))
        if kind == "recognize":
            if line.details["treatment"] != "deferred":
                raise ValidationError("Only deferred fees can be recognized.")
            recognized = line.recognitions.aggregate(v=Sum("amount"))["v"] or ZERO
            if value > line.net - credited - recognized:
                raise ValidationError("Recognition exceeds unearned revenue remaining.")
    elif kind == "fine_waiver":
        if not charge or charge.kind != "fine":
            raise ValidationError("Select the original late fee.")
        if value > charge.amount + (charge.credits.aggregate(v=Sum("amount"))["v"] or ZERO):
            raise ValidationError("Waiver exceeds the original fine remaining.")
    elif kind == "debit":
        if not invoice:
            raise ValidationError("Select an issued invoice for this charge.")
    elif kind == "refund_credit":
        if not credit or value > lot_available(credit, exclude_request=request):
            raise ValidationError("Refund exceeds unallocated advance credit available.")
        _cash(refs.get("target_account"))
    elif kind == "refund_deposit":
        if not allocation or value > deposit_available(allocation, exclude_request=request):
            raise ValidationError("Refund exceeds funded deposit available.")
        _cash(refs.get("target_account"))
    elif kind == "reverse_payment":
        if not payment or payment.state != "posted" or reversal_for(payment, exclude=request):
            raise ValidationError("Select an unreversed posted payment.")
        lot = payment.credit_lot
        if lot.refunds.exists() or Refund.objects.filter(allocation__credit=lot).exists():
            raise ValidationError(
                "Refunded payments cannot be reversed; retain their refund history."
            )
        pending = FinancialRequest.objects.filter(state="pending", credit=lot)
        if request:
            pending = pending.exclude(pk=request.pk)
        if pending.exists():
            raise ValidationError("Resolve pending credit reservations before reversal.")
        if day < payment.paid_on:
            raise ValidationError("A reversal cannot precede its payment.")
    elif kind == "void":
        if not invoice or active_allocations(invoice=invoice) or invoice.adjustments.exists():
            raise ValidationError("Only an unpaid, unadjusted invoice may be voided.")
    elif kind == "replace":
        if not invoice or invoice.state != "voided" or hasattr(invoice, "replacement"):
            raise ValidationError("Select a voided invoice without an existing replacement.")
    elif kind == "allocate":
        if not credit or not invoice or credit.student_id != invoice.student_id:
            raise ValidationError("Choose credit and invoice belonging to the same student.")
        if (
            value > lot_available(credit, exclude_request=request)
            or value > invoice_totals(invoice)["balance"]
        ):
            raise ValidationError("Allocation exceeds credit or outstanding balance.")
    elif kind in ("transfer", "opening"):
        _cash(refs.get("target_account"))
        if kind == "transfer":
            _cash(refs.get("source_account"))
            if refs["source_account"].pk == refs["target_account"].pk:
                raise ValidationError("Transfer accounts must differ.")
        elif JournalEntry.objects.filter(
            source_type="opening", lines__account=refs["target_account"]
        ).exists():
            raise ValidationError("This cash/bank account already has an opening entry.")
    elif kind == "payment":
        if not payment or payment.state != "pending":
            raise ValidationError("Select a pending payment.")
    elif kind == "exempt_fines":
        if not refs.get("student") or date.fromisoformat(payload["ends_on"]) < date.fromisoformat(
            payload["starts_on"]
        ):
            raise ValidationError("Choose a student and valid exemption dates.")
    elif kind == "discount":
        concession = ConcessionType.objects.get(pk=payload.get("concession_type"))
        if not concession.is_active or (concession.mode == "percent" and value > 100):
            raise ValidationError("Select an active concession and a valid value.")
        if not refs.get("student"):
            raise ValidationError("Choose the concession recipient.")
        if date.fromisoformat(payload["ends_on"]) < date.fromisoformat(payload["starts_on"]):
            raise ValidationError("Concession end must follow its start.")
    elif kind == "expense":
        expense = Expense.objects.get(pk=payload.get("expense"))
        if expense.amount != value or expense.category.account.kind != "expense":
            raise ValidationError("Expense amount or expense account is invalid.")
    elif kind == "opening_student":
        if not refs.get("student") or payload.get("mode") != "advance":
            raise ValidationError(
                "Student openings currently support verified advance credit only; "
                "bill receivables explicitly."
            )
    elif kind in ("close_period", "reopen_period"):
        period = refs.get("period")
        if not period or period.is_closed != (kind == "reopen_period"):
            raise ValidationError("Select a period in the appropriate state.")
    elif kind in ("close_year", "reopen_year"):
        from .models import FinancialYear

        year = FinancialYear.objects.get(pk=payload["year"])
        if year.is_closed != (kind == "reopen_year"):
            raise ValidationError("The financial year is already in that state.")
    elif kind == "reconcile":
        from .reconciliation import validate_reconciliation

        validate_reconciliation(refs["target_account"], payload, request=request)


@transaction.atomic
def request_action(actor, kind, *, amount_value=ZERO, day=None, reason, payload=None, **refs):
    permission = {
        "issue_invoice": "generate_invoices",
        "payment": "collect_payments",
        "allocate": "allocate_credit",
        "expense": "record_expenses",
        "reconcile": "reconcile_accounts",
        "close_period": "close_financial_periods",
        "close_year": "close_financial_periods",
        "reopen_period": "reopen_financial_periods",
        "reopen_year": "reopen_financial_periods",
        "opening": "manage_finance",
        "opening_student": "manage_finance",
        "transfer": "record_expenses",
        "discount": "manage_fees",
        "exempt_fines": "manage_fees",
    }.get(kind, "request_adjustments")
    require(actor, permission)
    settings = locked_config()
    day = day or school_day()
    if kind in ("issue_invoice", "void", "replace") and refs.get("invoice"):
        amount_value = refs["invoice"].total
    if kind in ("payment", "reverse_payment") and refs.get("payment"):
        amount_value = refs["payment"].amount
    value = amount(amount_value, settings, positive=False)
    if (
        kind
        not in (
            "issue_invoice",
            "exempt_fines",
            "void",
            "replace",
            "reverse_payment",
            "reconcile",
            "close_period",
            "reopen_period",
            "close_year",
            "reopen_year",
        )
        and not value
    ):
        raise ValidationError("Enter a positive amount.")
    if len(reason.strip()) < 8:
        raise ValidationError("Give a clear reason of at least eight characters.")
    payload = dict(payload or {})
    _validate(kind, value, day, payload, refs, settings)
    if kind in ("issue_invoice", "void", "replace", "reverse_payment", "payment"):
        duplicate = FinancialRequest.objects.filter(kind=kind, state="pending")
        duplicate = duplicate.filter(
            **{k: v for k, v in refs.items() if k in ("invoice", "payment")}
        )
        if duplicate.exists():
            raise ValidationError("This document already has a pending request.")
    if kind == "refund_fee":
        remaining = value
        funding = []
        for allocation in (
            refs["line"].allocations.select_related("credit").order_by("allocated_on", "created_at")
        ):
            if FinancialRequest.objects.filter(
                kind="reverse_payment", payment_id=allocation.credit.payment_id, state="pending"
            ).exists():
                continue
            used = ZERO
            for pending in FinancialRequest.objects.filter(
                kind="refund_fee", line=refs["line"], state="pending"
            ):
                used += sum(
                    (
                        amount(f["amount"], settings)
                        for f in pending.payload.get("funding", [])
                        if f["allocation"] == str(allocation.pk)
                    ),
                    ZERO,
                )
            piece = min(remaining, allocation_remaining(allocation) - used)
            if piece > 0:
                funding.append({"allocation": str(allocation.pk), "amount": str(piece)})
                remaining -= piece
        if remaining:
            raise ValidationError("The paid fee funding is reserved or no longer refundable.")
        payload["funding"] = funding
    # Store the affected student consistently; portal scoping never trusts submitted IDs.
    derived = refs.get("invoice") or refs.get("payment") or refs.get("credit")
    if derived:
        if refs.get("student") and refs["student"].pk != derived.student_id:
            raise ValidationError("The student does not match the source document.")
        refs["student"] = derived.student
    if refs.get("allocation"):
        refs["student"] = refs["allocation"].credit.student
    request = FinancialRequest.objects.create(
        kind=kind,
        amount=value,
        occurred_on=day,
        reason=reason.strip(),
        payload=payload,
        requested_by=actor,
        **refs,
    )
    event(actor, "request_" + kind, request.pk, student=request.student, reason=reason)
    return request


def _credit_note(actor, settings, request, value, *, kind="credit"):
    line, charge = request.line, request.charge
    original = line.net if line else charge.amount
    credits = (
        -(line.adjustments.aggregate(v=Sum("amount"))["v"] or ZERO)
        if line
        else -(charge.credits.aggregate(v=Sum("amount"))["v"] or ZERO)
    )
    paid = active_allocations(line=line) if line else active_allocations(charge=charge)
    release = max(ZERO, paid - (original - credits - value))
    allocations = (line.allocations if line else charge.allocations).select_related(
        "credit__student", "line"
    )
    for allocation in allocations.order_by("-created_at"):
        piece = min(release, allocation_remaining(allocation))
        if piece > 0:
            _release(actor, settings, allocation, piece, request, suffix="credit")
            release -= piece
    account = (
        control("fine")
        if charge and charge.kind == "fine"
        else control("adjustment")
        if charge
        else Account.objects.get(pk=line.details["account"])
    )
    postings = []
    if line and line.details["treatment"] == "deferred":
        recognized = line.recognitions.aggregate(v=Sum("amount"))["v"] or ZERO
        unearned = original - credits - recognized
        deferred_piece = min(value, unearned)
        if deferred_piece:
            postings.append((control("deferred"), request.student, deferred_piece, ZERO))
        if value > deferred_piece:
            recognized_piece = value - deferred_piece
            postings.append((account, None, recognized_piece, ZERO))
            RevenueRecognition.objects.create(line=line, request=request, amount=-recognized_piece)
    else:
        if line and line.details["treatment"] == "deposit":
            account = control("deposit_due")
        elif line and line.details["treatment"] == "opening":
            account = control("equity")
        if kind == "writeoff":
            account = control("adjustment")
        postings.append((account, request.student, value, ZERO))
    adjustment = InvoiceAdjustment.objects.create(
        invoice=request.invoice,
        line=line,
        reverses_charge=charge,
        kind=kind,
        amount=-value,
        occurred_on=request.occurred_on,
        reason=request.reason[:500],
        request=request,
        source_key=f"credit:{request.pk}",
    )
    postings.append((control("receivable"), request.student, ZERO, value))
    _post(
        actor,
        settings,
        source_key=adjustment.source_key,
        source_type="credit_note",
        source_id=adjustment.pk,
        day=request.occurred_on,
        memo=request.reason,
        lines=postings,
        request=request,
    )


def _refund(actor, settings, request, value, *, credit=None, allocation=None, suffix=""):
    source = control("advance" if credit else "deposit")
    refund = Refund.objects.create(
        request=request,
        student=request.student,
        credit=credit,
        allocation=allocation,
        amount=value,
        account=request.target_account,
    )
    _post(
        actor,
        settings,
        source_key=f"refund:{request.pk}:{suffix}",
        source_type="refund",
        source_id=refund.pk,
        day=request.occurred_on,
        memo=request.reason,
        request=request,
        lines=[(source, request.student, value, ZERO), (request.target_account, None, ZERO, value)],
    )


@transaction.atomic
def decide_request(actor, request_id, *, approve, reason):
    require(actor, "approve_finance")
    settings = locked_config()
    request = (
        FinancialRequest.objects.select_for_update(of=("self",))
        .select_related(
            "invoice",
            "payment",
            "credit",
            "allocation__credit",
            "line",
            "charge",
            "period",
            "target_account",
            "source_account",
            "student",
        )
        .get(pk=request_id)
    )
    if request.state != "pending" or request.requested_by_id == actor.pk:
        raise ValidationError(
            "A different authorized reviewer must decide each pending request once."
        )
    if len(reason.strip()) < 8:
        raise ValidationError("Explain the decision in at least eight characters.")
    senior = (
        (school_day() - request.occurred_on).days > settings.backdate_days
        or request.amount >= settings.senior_approval_threshold
        or request.kind.startswith("reopen")
        or request.kind in ("writeoff", "opening", "opening_student", "close_year")
    )
    if (
        request.kind == "issue_invoice"
        and request.invoice.lines.filter(details__treatment="opening").exists()
    ):
        senior = True
    if request.kind == "discount":
        kind = ConcessionType.objects.get(pk=request.payload["concession_type"])
        senior = senior or (
            kind.mode == "percent" and request.amount >= settings.senior_discount_percent
        )
    if senior:
        require(actor, "approve_senior_finance")
    refs = {
        name: getattr(request, name)
        for name in (
            "student",
            "invoice",
            "payment",
            "credit",
            "allocation",
            "line",
            "charge",
            "period",
            "source_account",
            "target_account",
        )
    }
    if approve:
        _validate(
            request.kind,
            request.amount,
            request.occurred_on,
            request.payload,
            refs,
            settings,
            request=request,
        )
    request.state = "approved" if approve else "rejected"
    request.reviewed_by, request.reviewed_at, request.decision_reason = (
        actor,
        school_now(),
        reason.strip(),
    )
    request.save()
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('schoolos.finance_request', %s, true)", [str(request.pk)])
    if not approve:
        if request.kind == "payment":
            Payment.objects.filter(pk=request.payment_id).update(state="rejected")
        if request.kind == "reconcile":
            from .models import ReconciliationLine

            ReconciliationLine.objects.filter(reconciliation__request=request).update(
                is_active=False
            )
    else:
        _execute(actor, settings, request)
    event(actor, "request_" + request.state, request.pk, student=request.student, reason=reason)
    return request


def _execute(actor, settings, r):
    kind, value, day = r.kind, r.amount, r.occurred_on
    if kind == "issue_invoice":
        r.invoice.state, r.invoice.approval = "approved", r
        r.invoice.save(update_fields=["state", "approval", "updated_at"])
    elif kind == "payment":
        _post_payment(actor, settings, r.payment, r.payload.get("allocations", []), request=r)
    elif kind == "allocate":
        _allocate(actor, settings, r.credit, r.invoice, value, day, f"request:{r.pk}", request=r)
    elif kind == "exempt_fines":
        from .models import LateFeeExemption

        LateFeeExemption.objects.create(
            student=r.student,
            starts_on=r.payload["starts_on"],
            ends_on=r.payload["ends_on"],
            request=r,
        )
    elif kind == "discount":
        ConcessionAward.objects.create(
            student=r.student,
            concession_type_id=r.payload["concession_type"],
            category_id=r.payload.get("category") or None,
            value=value,
            starts_on=r.payload["starts_on"],
            ends_on=r.payload["ends_on"],
            notes=r.reason[:300],
            request=r,
        )
    elif kind in ("credit", "writeoff", "fine_waiver", "refund_fee"):
        if kind == "refund_fee":
            from .models import Allocation

            for item in r.payload["funding"]:
                allocation = Allocation.objects.select_related("credit__student", "line").get(
                    pk=item["allocation"]
                )
                _release(actor, settings, allocation, item["amount"], r, suffix="refund")
        _credit_note(
            actor,
            settings,
            r,
            value,
            kind="writeoff"
            if kind == "writeoff"
            else "waiver"
            if kind == "fine_waiver"
            else "credit",
        )
        if kind == "refund_fee":
            from .models import Allocation

            for index, item in enumerate(r.payload["funding"]):
                allocation = Allocation.objects.select_related("credit").get(pk=item["allocation"])
                _refund(
                    actor,
                    settings,
                    r,
                    amount(item["amount"], settings),
                    credit=allocation.credit,
                    suffix=str(index),
                )
    elif kind == "refund_credit":
        _refund(actor, settings, r, value, credit=r.credit)
    elif kind == "refund_deposit":
        _refund(actor, settings, r, value, allocation=r.allocation)
    elif kind == "reverse_payment":
        lot = r.payment.credit_lot
        for allocation in lot.allocations.select_related("credit__student", "line"):
            active = allocation_remaining(allocation)
            if active:
                _release(actor, settings, allocation, active, r)
        _post(
            actor,
            settings,
            source_key=f"reversal:{r.pk}",
            source_type="payment_reversal",
            source_id=r.pk,
            day=day,
            memo=r.reason,
            request=r,
            reversal_of=JournalEntry.objects.get(source_key=f"payment:{r.payment_id}"),
            lines=[
                (control("advance"), r.student, r.payment.amount, ZERO),
                (r.payment.method.account, None, ZERO, r.payment.amount),
            ],
        )
    elif kind == "void":
        original = JournalEntry.objects.filter(source_key=f"invoice:{r.invoice_id}").first()
        if original:
            _post(
                actor,
                settings,
                source_key=f"void:{r.pk}",
                source_type="invoice_void",
                source_id=r.pk,
                day=day,
                memo=r.reason,
                request=r,
                reversal_of=original,
                lines=[
                    (item.account, item.student, item.credit, item.debit)
                    for item in original.lines.select_related("account", "student")
                ],
            )
        r.invoice.state = "voided"
        r.invoice.save(update_fields=["state", "updated_at"])
    elif kind == "replace":
        from .billing import BillingContext, _create_invoice

        _create_invoice(
            actor,
            r.student,
            r.invoice.cycle,
            settings,
            BillingContext(r.invoice.cycle, [r.student]),
            replacement=r.invoice,
            generation_key=f"replacement:{r.pk}",
        )
    elif kind == "debit":
        adjustment = InvoiceAdjustment.objects.create(
            invoice=r.invoice,
            kind="debit",
            amount=value,
            occurred_on=day,
            reason=r.reason[:500],
            request=r,
            source_key=f"debit:{r.pk}",
        )
        _post(
            actor,
            settings,
            source_key=adjustment.source_key,
            source_type="adjustment",
            source_id=adjustment.pk,
            day=day,
            memo=r.reason,
            request=r,
            lines=[
                (control("receivable"), r.student, value, ZERO),
                (control("revenue"), None, ZERO, value),
            ],
        )
    elif kind == "recognize":
        RevenueRecognition.objects.create(line=r.line, request=r, amount=value)
        _post(
            actor,
            settings,
            source_key=f"recognize:{r.pk}",
            source_type="recognition",
            source_id=r.pk,
            day=day,
            memo=r.reason,
            request=r,
            lines=[
                (control("deferred"), r.student, value, ZERO),
                (Account.objects.get(pk=r.line.details["account"]), None, ZERO, value),
            ],
        )
    elif kind in ("opening", "transfer", "opening_student"):
        if kind == "opening_student":
            CreditLot.objects.create(student=r.student, opening_request=r, amount=value)
            postings = [
                (control("equity"), None, value, ZERO),
                (control("advance"), r.student, ZERO, value),
            ]
        else:
            postings = [
                (r.target_account, None, value, ZERO),
                (r.source_account if kind == "transfer" else control("equity"), None, ZERO, value),
            ]
        _post(
            actor,
            settings,
            source_key=f"{kind}:{r.pk}",
            source_type=kind,
            source_id=r.pk,
            day=day,
            memo=r.reason,
            lines=postings,
            request=r,
        )
    elif kind == "expense":
        expense = Expense.objects.select_related("category__account").get(pk=r.payload["expense"])
        _post(
            actor,
            settings,
            source_key=f"expense:{expense.pk}",
            source_type="expense",
            source_id=expense.pk,
            day=day,
            memo=expense.description,
            request=r,
            lines=[
                (expense.category.account, None, value, ZERO),
                (control("payable"), None, ZERO, value),
            ],
        )
    elif kind == "reconcile":
        from .reconciliation import approve_reconciliation

        approve_reconciliation(r)
    elif kind in ("close_period", "reopen_period", "close_year", "reopen_year"):
        from .reconciliation import change_period

        change_period(r)
    from .notifications import notify

    if r.student:
        notify(
            r.student,
            "adjustment_approved",
            f"decision:{r.pk}",
            invoice=r.invoice,
            payment=r.payment,
        )
