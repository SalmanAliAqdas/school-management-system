from django.db.models import Q

from people.models import Student

from .common import capable, config
from .models import FinanceNotice, Invoice, Payment


def students_visible_to(user):
    rows = Student.objects.all()
    settings = config()
    if not capable(user, "access_finance"):
        return rows.none()
    if capable(user, "view_all_finance"):
        return rows
    scope = Q(pk__in=[])
    if settings and settings.student_portal and user.has_perm("accounts.access_student_dashboard"):
        scope |= Q(user=user)
    if settings and settings.guardian_portal and user.has_perm("accounts.access_parent_dashboard"):
        scope |= Q(guardian_links__guardian__user=user)
    return rows.filter(scope).distinct()


def invoices_visible_to(user):
    rows = Invoice.objects.filter(student__in=students_visible_to(user)).select_related(
        "student", "academic_year", "cycle"
    )
    return (
        rows if capable(user, "view_all_finance") else rows.filter(state__in=["issued", "voided"])
    )


def payments_visible_to(user):
    rows = Payment.objects.filter(student__in=students_visible_to(user)).select_related(
        "student", "method"
    )
    return rows if capable(user, "view_all_finance") else rows.filter(state="posted")


def notices_visible_to(user):
    return FinanceNotice.objects.filter(
        recipient=user, student__in=students_visible_to(user)
    ).select_related("student", "invoice", "payment")
