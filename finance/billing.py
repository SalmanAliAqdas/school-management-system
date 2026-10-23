from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from academics.models import AcademicYear
from attendance.calendar import SchoolCalendar
from people.models import Enrollment, GuardianStudent

from .common import (
    ZERO,
    amount,
    control,
    event,
    locked_config,
    next_number,
    require,
    rounded,
    school_day,
    school_now,
    school_snapshot,
)
from .ledger import _post, period_for
from .models import (
    BillingCycle,
    ConcessionAward,
    ConcessionUse,
    FeeAssignment,
    FeeStructure,
    Invoice,
    InvoiceLine,
    OneTimeCharge,
)


def adjusted_due_date(cycle, settings):
    due = cycle.due_on
    if settings.shift_holiday_due_dates:
        calendar = SchoolCalendar(cycle.academic_year)
        for _ in range(31):
            reason = (
                calendar.reason(due, staff=True)
                if calendar.policy(due)
                else ("Weekly holiday" if due.weekday() > 4 else "")
            )
            if not reason:
                return due
            due += timedelta(days=1)
        raise ValidationError(
            "No working due date was found within 31 days; set an explicit due date."
        )
    return due


class BillingContext:
    def __init__(self, cycle, students):
        self.cycle = cycle
        self.enrollments = defaultdict(list)
        for row in (
            Enrollment.objects.filter(
                academic_year=cycle.academic_year,
                student__in=students,
                started_on__lte=cycle.ends_on,
            )
            .filter(Q(ended_on__isnull=True) | Q(ended_on__gte=cycle.starts_on))
            .select_related("student", "section__school_class")
        ):
            self.enrollments[row.student_id].append(row)
        self.structures = list(
            FeeStructure.objects.filter(
                academic_year=cycle.academic_year,
                is_active=True,
                frequency__in=[cycle.frequency, "once"],
                starts_on__lte=cycle.ends_on,
                ends_on__gte=cycle.starts_on,
            )
            .select_related("section", "school_class")
            .prefetch_related("lines__category__income_account")
        )
        self.by_id = {s.pk: s for s in self.structures}
        self.assignments = defaultdict(list)
        for row in FeeAssignment.objects.filter(
            student__in=students,
            structure_id__in=self.by_id,
            starts_on__lte=cycle.ends_on,
            ends_on__gte=cycle.starts_on,
        ):
            self.assignments[row.student_id].append(row)
        self.awards = defaultdict(list)
        for row in ConcessionAward.objects.filter(
            student__in=students,
            request__state="approved",
            starts_on__lte=cycle.issue_on,
            ends_on__gte=cycle.issue_on,
            concession_type__is_active=True,
        ).select_related("concession_type"):
            self.awards[row.student_id].append(row)
        self.once = set(
            OneTimeCharge.objects.filter(student__in=students)
            .filter(Q(academic_year=cycle.academic_year) | Q(academic_year__isnull=True))
            .values_list("student_id", "category_id")
        )
        self.concessions_used = set(
            ConcessionUse.objects.filter(
                award__student__in=students, once_key__isnull=False
            ).values_list("award_id", flat=True)
        )


def _selected_lines(context, student, enrollment, day):
    choices = defaultdict(list)
    assignments = context.assignments[student.pk]
    for structure in context.structures:
        if (
            not structure.starts_on <= day <= structure.ends_on
            or structure.school_class_id != enrollment.section.school_class_id
        ):
            continue
        matched = [
            a
            for a in assignments
            if a.structure_id == structure.pk and a.starts_on <= day <= a.ends_on
        ]
        if structure.assignment_only and not matched:
            continue
        if structure.section_id and structure.section_id != enrollment.section_id and not matched:
            continue
        for line in structure.lines.all():
            category = line.category
            if (
                not category.is_active
                or category.starts_on > day
                or (category.ends_on and category.ends_on < day)
            ):
                continue
            assignment = next(
                (a for a in matched if a.category_id in (None, line.category_id)), None
            )
            rank = 200 if assignment else 100 if structure.section_id else 0
            if structure.assignment_only and not assignment:
                continue
            choices[line.category_id].append((rank, structure, line, assignment))
    result = []
    for candidates in choices.values():
        highest = max(c[0] for c in candidates)
        candidates = [c for c in candidates if c[0] == highest]
        families = {c[1].family for c in candidates}
        if len(families) > 1:
            raise ValidationError(
                "Conflicting fee structures apply to the same category and date. "
                "Resolve the overlap before billing."
            )
        result.append(max(candidates, key=lambda c: (c[1].starts_on, c[1].revision)))
    return result


def _sibling_eligible(student, day):
    children = (
        GuardianStudent.objects.filter(
            guardian__students=student, student__enrollments__started_on__lte=day
        )
        .filter(
            Q(student__enrollments__ended_on__isnull=True)
            | Q(student__enrollments__ended_on__gte=day)
        )
        .values("student_id")
        .distinct()
    )
    return children.count() >= 2


def calculate_charges(student, cycle, settings, context):
    enrollments = context.enrollments[student.pk]
    if not enrollments:
        return []
    days = (cycle.ends_on - cycle.starts_on).days + 1
    dates = [cycle.starts_on + timedelta(days=i) for i in range(days)]
    if settings.billing_rule == "start":
        dates = [cycle.starts_on]
    elif settings.billing_rule == "any":
        dates = [min(max(e.started_on, cycle.starts_on) for e in enrollments)]
    grouped = {}
    for day in dates:
        enrollment = next(
            (
                e
                for e in enrollments
                if e.started_on <= day and (not e.ended_on or e.ended_on >= day)
            ),
            None,
        )
        if not enrollment:
            continue
        for _, structure, line, assignment in _selected_lines(context, student, enrollment, day):
            once = not line.category.recurring or structure.frequency == "once"
            if once and (student.pk, line.category_id) in context.once:
                continue
            key = (line.category_id, line.pk, assignment.pk if assignment else None, enrollment.pk)
            if once:
                key = (line.category_id, "once")
            unit = (
                assignment.amount_override
                if assignment
                and assignment.amount_override is not None
                and assignment.category_id == line.category_id
                else line.amount
            )
            if key not in grouped:
                grouped[key] = {
                    "category": line.category,
                    "fee_line": line,
                    "assignment": assignment,
                    "enrollment": enrollment,
                    "gross": ZERO,
                    "days": 0,
                    "unit": unit,
                    "once": once,
                    "structure": structure,
                }
            row = grouped[key]
            row["days"] += 1
            if once:
                row["gross"] = unit
            else:
                row["gross"] += unit / Decimal(days) if settings.billing_rule == "prorata" else unit
    rows = list(grouped.values())
    by_category = defaultdict(list)
    for row in rows:
        row["gross"] = rounded(row["gross"], settings)
        row["discount"] = ZERO
        row["concessions"] = []
        by_category[row["category"].pk].append(row)
    for category_id, parts in by_category.items():
        if parts[0]["category"].treatment in ("deposit", "opening"):
            continue
        awards = [
            a
            for a in context.awards[student.pk]
            if a.category_id in (None, category_id)
            and (not a.concession_type.one_time or a.pk not in context.concessions_used)
        ]
        if any(
            a.concession_type.eligibility == "siblings" for a in awards
        ) and not _sibling_eligible(student, cycle.issue_on):
            awards = [a for a in awards if a.concession_type.eligibility != "siblings"]
        if len(awards) > 1 and not (
            settings.allow_discount_stacking and all(a.concession_type.stackable for a in awards)
        ):
            raise ValidationError(
                "Multiple concessions overlap. Explicitly authorize stacking or resolve the awards."
            )
        gross = sum((r["gross"] for r in parts), ZERO)
        remaining = gross
        ceiling = rounded(gross * settings.discount_ceiling_percent / 100, settings)
        used = ZERO
        for award in sorted(
            awards,
            key=lambda a: (
                a.concession_type.mode != "fixed",
                a.concession_type.priority,
                str(a.pk),
            ),
        ):
            value = (
                award.value
                if award.concession_type.mode == "fixed"
                else rounded(remaining * award.value / 100, settings)
            )
            if award.concession_type.per_charge_cap is not None:
                value = min(value, award.concession_type.per_charge_cap)
            value = min(value, remaining, max(ceiling - used, ZERO))
            if value <= 0:
                continue
            distributed = ZERO
            for index, row in enumerate(parts):
                share = (
                    value - distributed
                    if index == len(parts) - 1
                    else rounded(value * row["gross"] / gross, settings)
                )
                share = min(share, row["gross"] - row["discount"])
                row["discount"] += share
                distributed += share
                if share:
                    row["concessions"].append(
                        {
                            "award": str(award.pk),
                            "name": award.concession_type.name,
                            "amount": str(share),
                            "once": award.concession_type.one_time,
                        }
                    )
            remaining -= distributed
            used += distributed
    return rows


def _create_invoice(
    actor, student, cycle, settings, context, *, replacement=None, generation_key=None
):
    key = generation_key or f"cycle:{cycle.pk}:student:{student.pk}"
    existing = Invoice.objects.filter(generation_key=key).first()
    if existing:
        return existing, False
    if replacement:
        for original_line in replacement.lines.select_related("category"):
            context.once.discard((student.pk, original_line.category_id))
        for use in ConcessionUse.objects.filter(
            invoice_line__invoice=replacement, once_key__isnull=False
        ):
            context.concessions_used.discard(use.award_id)
    rows = calculate_charges(student, cycle, settings, context)
    if not rows:
        return None, False
    subtotal = sum((r["gross"] for r in rows), ZERO)
    discount = sum((r["discount"] for r in rows), ZERO)
    amount(subtotal, settings, positive=False)
    amount(discount, settings, positive=False)
    invoice = Invoice.objects.create(
        generation_key=key,
        number=next_number("invoice", cycle.issue_on, settings),
        student=student,
        academic_year=cycle.academic_year,
        cycle=cycle,
        replaces=replacement,
        issue_on=cycle.issue_on,
        due_on=adjusted_due_date(cycle, settings),
        currency=settings.currency,
        subtotal=subtotal,
        discount=discount,
        total=subtotal - discount,
        created_by=actor,
        snapshot={
            "school": school_snapshot(settings),
            "student": str(student),
            "admission": student.admission_number,
            "cycle": cycle.name,
            "year": cycle.academic_year.name,
            "billing_rule": settings.billing_rule,
            "guardians": list(student.guardians.values_list("first_name", "last_name"))
            if settings.include_guardian_names
            else [],
        },
    )
    for row in rows:
        InvoiceLine.objects.create(
            invoice=invoice,
            category=row["category"],
            enrollment=row["enrollment"],
            fee_line=row["fee_line"],
            assignment=row["assignment"],
            description=row["category"].name,
            gross=row["gross"],
            discount=row["discount"],
            net=row["gross"] - row["discount"],
            details={
                "days": row["days"],
                "cycle_days": (cycle.ends_on - cycle.starts_on).days + 1,
                "unit": str(row["unit"]),
                "structure": str(row["structure"]),
                "treatment": row["category"].treatment,
                "account": row["category"].income_account_id,
                "refundable": row["category"].refundable,
                "late_fee_eligible": row["category"].late_fee_eligible,
                "class": row["enrollment"].section.school_class.name,
                "section": row["enrollment"].section.name,
                "roll": row["enrollment"].roll_number,
                "once": row["once"],
                "concessions": row["concessions"],
            },
        )
    event(actor, "invoice_generated", invoice.pk, student=student)
    return invoice, True


@transaction.atomic
def generate_invoices(actor, cycle_id, students):
    require(actor, "generate_invoices")
    settings = locked_config()
    cycle = BillingCycle.objects.select_related("academic_year").get(pk=cycle_id)
    year = AcademicYear.objects.select_for_update(of=("self",)).get(pk=cycle.academic_year_id)
    if year.status != "open":
        raise ValidationError("Generate prospective bills only in an open academic year.")
    students = list(students)
    if len(students) > 200:
        raise ValidationError("Generate at most 200 students per confirmed batch.")
    context = BillingContext(cycle, students)
    outcome = {"generated": [], "skipped": [], "failed": []}
    for student in students:
        try:
            with transaction.atomic():
                invoice, created = _create_invoice(actor, student, cycle, settings, context)
        except ValidationError as exc:
            outcome["failed"].append({"student": student, "errors": exc.messages})
        else:
            outcome["generated" if created else "skipped"].append(invoice or student)
    return outcome


@transaction.atomic
def issue_invoice(actor, invoice_id):
    require(actor, "generate_invoices")
    settings = locked_config()
    invoice = (
        Invoice.objects.select_for_update(of=("self",))
        .select_related("student", "approval", "cycle")
        .get(pk=invoice_id)
    )
    if invoice.state == "issued":
        return invoice
    if invoice.state not in ("draft", "approved"):
        raise ValidationError("Only a draft/approved invoice can be issued.")
    needs_approval = (
        settings.invoice_approval or (school_day() - invoice.issue_on).days > settings.backdate_days
    )
    if needs_approval and (
        invoice.state != "approved"
        or not invoice.approval_id
        or invoice.approval.state != "approved"
    ):
        raise ValidationError("Obtain independent invoice approval before issue.")
    if invoice.lines.filter(details__treatment="opening").exists() and (
        not invoice.approval_id
        or invoice.approval.state != "approved"
        or not invoice.approval.reviewed_by.has_perm("finance.approve_senior_finance")
    ):
        raise ValidationError("Opening receivables require independent senior approval.")
    period_for(invoice.issue_on)
    postings = []
    if invoice.total:
        postings.append((control("receivable"), invoice.student, invoice.total, ZERO))
    lines = list(
        invoice.lines.select_related(
            "category__income_account", "enrollment__section__school_class"
        )
    )
    if sum((item.net for item in lines), ZERO) != invoice.total:
        raise ValidationError("Invoice totals no longer match its preserved lines.")
    for line in lines:
        treatment = line.details["treatment"]
        if treatment == "earned":
            postings.extend(
                [
                    (line.category.income_account, None, ZERO, line.gross),
                    (control("discount"), invoice.student, line.discount, ZERO),
                ]
            )
        else:
            account = control(
                "deposit_due"
                if treatment == "deposit"
                else "equity"
                if treatment == "opening"
                else "deferred"
            )
            postings.append((account, invoice.student, ZERO, line.net))
        if line.details.get("once"):
            year = invoice.academic_year if line.category.one_time_scope == "year" else None
            existing = OneTimeCharge.objects.filter(
                student=invoice.student, category=line.category, academic_year=year
            ).first()
            if existing and existing.invoice_id != invoice.replaces_id:
                raise ValidationError(
                    "A one-time fee was already charged. Use an authorized replacement"
                    " rather than charging again."
                )
            if not existing:
                OneTimeCharge.objects.create(
                    student=invoice.student,
                    category=line.category,
                    academic_year=year,
                    invoice=invoice,
                )
        for concession in line.details.get("concessions", []):
            award = ConcessionAward.objects.get(pk=concession["award"])
            used = (
                ConcessionUse.objects.filter(once_key=award.pk).first()
                if concession["once"]
                else None
            )
            if used and used.invoice_line.invoice_id not in (invoice.pk, invoice.replaces_id):
                raise ValidationError("This one-time concession was consumed by another invoice.")
            ConcessionUse.objects.create(
                award=award,
                invoice_line=line,
                amount=concession["amount"],
                once_key=award.pk if concession["once"] and not used else None,
            )
    _post(
        actor,
        settings,
        source_key=f"invoice:{invoice.pk}",
        source_type="invoice",
        source_id=invoice.pk,
        day=invoice.issue_on,
        memo=f"Invoice {invoice.number}",
        lines=postings,
        request=invoice.approval,
    )
    first = lines[0] if lines else None
    invoice.snapshot = {
        **invoice.snapshot,
        "number": invoice.number,
        "issued_at": school_now().isoformat(),
        "subtotal": str(invoice.subtotal),
        "discount": str(invoice.discount),
        "total": str(invoice.total),
        "class": first.details["class"] if first else "",
        "section": first.details["section"] if first else "",
        "roll": first.details["roll"] if first else "",
        "issue_on": invoice.issue_on.isoformat(),
        "due_on": invoice.due_on.isoformat(),
        "lines": [
            {
                "description": item.description,
                "gross": str(item.gross),
                "discount": str(item.discount),
                "net": str(item.net),
                **item.details,
            }
            for item in lines
        ],
        "issued_by": actor.display_name,
        "approval_by": invoice.approval.reviewed_by.display_name
        if invoice.approval_id
        else "Not required by configured policy",
    }
    invoice.state = "issued"
    invoice.version += 1
    invoice.save()
    from .notifications import notify

    notify(invoice.student, "invoice_issued", f"issued:{invoice.pk}", invoice=invoice)
    event(actor, "invoice_issued", invoice.pk, student=invoice.student)
    return invoice
