from django.contrib.auth import get_user_model
from django.db import transaction

from people.models import GuardianStudent

from .common import config, require, school_day
from .models import FinanceNotice, Invoice


def notify(student, kind, key, *, invoice=None, payment=None):
    settings = config()
    users = set()
    if settings and settings.guardian_portal:
        users.update(
            GuardianStudent.objects.filter(
                student=student, guardian__user__is_active=True
            ).values_list("guardian__user_id", flat=True)
        )
    if settings and settings.student_portal and student.user_id:
        users.add(student.user_id)
    active = get_user_model().objects.filter(pk__in=users, is_active=True)
    FinanceNotice.objects.bulk_create(
        [
            FinanceNotice(
                recipient=user,
                student=student,
                invoice=invoice,
                payment=payment,
                kind=kind,
                event_key=key,
            )
            for user in active
        ],
        ignore_conflicts=True,
    )


@transaction.atomic
def send_reminders(actor):
    require(actor, "generate_invoices")
    from .common import locked_config
    from .payments import invoice_totals

    settings = locked_config()
    count = 0
    today = school_day()
    for invoice in Invoice.objects.filter(state="issued").select_related("student"):
        balance = invoice_totals(invoice)["balance"]
        if balance <= 0:
            continue
        delta = (today - invoice.due_on).days
        kind = (
            "upcoming_due"
            if -settings.reminder_days_before <= delta <= 0
            else "overdue"
            if delta > 0
            else None
        )
        if not kind:
            continue
        interval = max(settings.reminder_repeat_days, 1)
        bucket = max(delta, 0) // interval
        notify(invoice.student, kind, f"reminder:{kind}:{invoice.pk}:{bucket}", invoice=invoice)
        count += 1
    return count
