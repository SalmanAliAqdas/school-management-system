import base64
import hashlib
import json
import string
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction

from attendance.calendar import school_now
from audit.services import record_event
from core.models import SchoolSettings

from .models import LIMIT, Account, DocumentCounter, FinanceEvent, FinanceSettings

ZERO = Decimal("0")
HUNDRED = Decimal("100")
CONTROL_KINDS = {
    "cash": "asset",
    "bank": "asset",
    "receivable": "asset",
    "revenue": "income",
    "deferred": "liability",
    "advance": "liability",
    "deposit": "liability",
    "deposit_due": "liability",
    "discount": "contra_income",
    "fine": "income",
    "expense": "expense",
    "payable": "liability",
    "adjustment": "expense",
    "equity": "equity",
}


def capable(actor, permission):
    return actor.is_authenticated and actor.is_active and actor.has_perm(f"finance.{permission}")


def require(actor, permission, *, staff=True):
    if (
        not capable(actor, "access_finance")
        or not capable(actor, permission)
        or (staff and not capable(actor, "view_all_finance"))
    ):
        raise PermissionDenied


def school_day():
    return school_now().date()


def config():
    return FinanceSettings.objects.first()


def locked_config():
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("Finance changes require an atomic transaction.")
    settings = FinanceSettings.objects.select_for_update(of=("self",)).filter(pk=1).first()
    if not settings:
        raise ValidationError("Initialize Finance Settings before recording financial activity.")
    return settings


def rounded(value, settings):
    return Decimal(value).quantize(
        Decimal(1).scaleb(-settings.decimal_places), rounding=ROUND_HALF_UP
    )


def amount(value, settings, *, positive=True, signed=False):
    if isinstance(value, (float, bool)):
        raise ValidationError("Use an exact decimal amount.")
    try:
        result = Decimal(str(value))
        if not result.is_finite() or abs(result) > LIMIT:
            raise ValueError
        if (
            (not signed and result < 0)
            or (positive and result == 0)
            or result != rounded(result, settings)
        ):
            raise ValueError
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(
            f"Enter a valid amount with at most {settings.decimal_places} decimal places."
        ) from exc
    return result


def validate_number_format(pattern):
    fields = []
    try:
        for literal, field, spec, conversion in string.Formatter().parse(pattern):
            if any(ch not in string.ascii_letters + string.digits + " _./-" for ch in literal):
                raise ValueError
            if field is not None:
                if (
                    conversion
                    or field not in ("year", "seq")
                    or (field == "year" and spec)
                    or (
                        field == "seq"
                        and spec not in ("03d", "04d", "05d", "06d", "07d", "08d", "09d")
                    )
                ):
                    raise ValueError
                fields.append(field)
        if (
            fields.count("year") != 1
            or fields.count("seq") != 1
            or len(pattern.format(year=2026, seq=1)) > 45
        ):
            raise ValueError
    except (ValueError, KeyError, IndexError) as exc:
        raise ValidationError(
            "Use a literal prefix, one {year} and one padded {seq:06d}; no other format fields."
        ) from exc


def next_number(kind, day, settings):
    counter, _ = DocumentCounter.objects.get_or_create(kind=kind, year=day.year)
    counter = DocumentCounter.objects.select_for_update(of=("self",)).get(pk=counter.pk)
    pattern = settings.invoice_format if kind == "invoice" else settings.receipt_format
    validate_number_format(pattern)
    result = pattern.format(year=day.year, seq=counter.next_number)
    counter.next_number += 1
    counter.save(update_fields=["next_number"])
    return result


def fingerprint(data):
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, cls=DjangoJSONEncoder).encode()
    ).hexdigest()


def image_bytes(field):
    if not field:
        return None
    try:
        with field.open("rb") as file:
            data = file.read(2 * 1024 * 1024 + 1)
        return base64.b64encode(data).decode("ascii") if len(data) <= 2 * 1024 * 1024 else None
    except OSError:
        return None


def school_snapshot(settings):
    school = SchoolSettings.objects.first()
    result = {
        key: getattr(school, key, "") for key in ("name", "address", "phone", "email", "timezone")
    }
    result["name"] = result["name"] or "RumiWare SchoolOS"
    result.update(
        currency=settings.currency,
        symbol=settings.symbol,
        decimal_places=settings.decimal_places,
        logo=image_bytes(school.logo) if school else None,
    )
    return result


def event(actor, action, target, *, student=None, reason=""):
    FinanceEvent.objects.create(
        actor=actor, action=action, target=str(target)[:80], student=student, reason=reason[:1000]
    )
    record_event(f"finance.{action}", actor=actor, target=target)


def control(name):
    row = Account.objects.filter(control=name, is_active=True).order_by("pk").first()
    if not row:
        raise ValidationError(
            f"Configure an active {name.replace('_', ' ')} control account first."
        )
    return row


@transaction.atomic
def initialize(actor):
    require(actor, "manage_finance")
    school = SchoolSettings.objects.first()
    settings, _ = FinanceSettings.objects.get_or_create(
        pk=1, defaults={"currency": school.currency if school else "PKR"}
    )
    locked_config()
    for code, name, role in [
        ("1000", "Cash", "cash"),
        ("1010", "Bank, manual recording", "bank"),
        ("1100", "Student receivables", "receivable"),
        ("2000", "Student advance credits", "advance"),
        ("2010", "Refundable deposits held", "deposit"),
        ("2020", "Uncollected deposit charges", "deposit_due"),
        ("2100", "Deferred fee revenue", "deferred"),
        ("2200", "Expense payables", "payable"),
        ("3000", "Opening equity", "equity"),
        ("4000", "Earned school fees", "revenue"),
        ("4010", "Late-fee income", "fine"),
        ("4100", "Discounts and concessions", "discount"),
        ("5000", "Operating expenses", "expense"),
        ("5100", "Authorized write-offs", "adjustment"),
    ]:
        Account.objects.get_or_create(
            code=code, defaults={"name": name, "control": role, "kind": CONTROL_KINDS[role]}
        )
    event(actor, "initialized", settings.pk)
    return settings
