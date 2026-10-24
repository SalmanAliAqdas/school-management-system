from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone

from attendance.models import StaffAttendance, StudentAttendance
from attendance.reporting import summary
from certificates.models import DocumentRequest
from communications.models import Publication
from examinations.models import ExamSession, PublishedResult
from finance.models import Expense, FinancialRequest, Invoice, Payment
from finance.payments import reversal_for
from hr.models import Qualification, TrainingRecord
from inventory.models import StockMovement
from library.models import Book, Copy, Loan, Reservation
from payroll.models import Payslip
from people.models import Enrollment, Student
from transport.models import StudentAssignment, Vehicle, VehicleRecord

ZERO = Decimal("0")


def _attendance(year, start, end, *, staff=False):
    model = StaffAttendance if staff else StudentAttendance
    rows = model.objects.filter(
        register__state="final",
        register__academic_year=year,
        attendance_on__range=(start, end),
    )
    return summary(rows, staff=staff)


def _collections(start, end):
    total = ZERO
    for payment in Payment.objects.filter(state="posted", paid_on__range=(start, end)):
        reverse = reversal_for(payment)
        if not reverse or reverse.occurred_on > end:
            total += payment.amount
    return total


def executive_metrics(user, academic_year, starts_on, ends_on):
    year, start, end = academic_year, starts_on, ends_on
    placements = Enrollment.objects.filter(academic_year=year, started_on__lte=end).filter(
        Q(ended_on__isnull=True) | Q(ended_on__gte=start)
    )
    metrics = {
        "active_students": placements.values("student_id").distinct().count(),
        "new_admissions": Student.objects.filter(admission_date__range=(start, end)).count(),
        "withdrawn": Enrollment.objects.filter(
            academic_year=year, ended_on__range=(start, end), exit_reason="withdraw"
        ).count(),
        "classes": list(
            placements.values("section__school_class__name")
            .annotate(total=Count("student_id", distinct=True))
            .order_by("section__school_class__sort_order")
        ),
        "student_attendance": _attendance(year, start, end),
        "staff_attendance": _attendance(year, start, end, staff=True),
        "published_results": PublishedResult.objects.filter(
            publication__session__academic_year=year,
            publication__session__state__in=["published", "archived"],
        ).count(),
        "library": {
            "titles": Book.objects.count(),
            "available": Copy.objects.filter(status="available").count(),
            "loans": Loan.objects.filter(state="issued").count(),
            "overdue": Loan.objects.filter(state="issued", due_at__lt=timezone.now()).count(),
            "reservations": Reservation.objects.filter(state__in=["queued", "available"]).count(),
        },
        "transport": {
            "vehicles": Vehicle.objects.filter(status="active").count(),
            "assigned": StudentAssignment.objects.filter(starts_on__lte=end)
            .filter(Q(ends_on__isnull=True) | Q(ends_on__gte=start))
            .count(),
        },
        "events": Publication.objects.filter(
            kind="event", state="published", starts_at__date__range=(start, end)
        ).count(),
        "pending": (
            FinancialRequest.objects.filter(state="pending").count()
            + DocumentRequest.objects.filter(state__in=["requested", "draft", "approved"]).count()
        ),
    }
    if user.has_perm("finance.view_finance_reports"):
        issued = Invoice.objects.filter(state="issued", issue_on__range=(start, end))
        metrics["finance"] = {
            "invoiced": issued.aggregate(v=Sum("total"))["v"] or ZERO,
            "collections": _collections(start, end),
            "approved_expenses": Expense.objects.filter(
                request__state="approved", occurred_on__range=(start, end)
            ).aggregate(v=Sum("amount"))["v"]
            or ZERO,
        }
    if user.has_perm("payroll.view_all_payroll"):
        slips = Payslip.objects.filter(
            run__period__ends_on__gte=start,
            run__period__starts_on__lte=end,
            state__in=["released", "paid"],
        )
        metrics["payroll"] = {
            "obligation": slips.aggregate(v=Sum("net"))["v"] or ZERO,
            "paid": slips.filter(state="paid").aggregate(v=Sum("net"))["v"] or ZERO,
            "unpaid": slips.filter(state="released").aggregate(v=Sum("net"))["v"] or ZERO,
        }
    return metrics


def data_quality(year):
    today = timezone.localdate()
    return [
        (
            "Students without a current enrollment",
            Student.objects.filter(is_active=True).exclude(enrollments__is_active=True).count(),
            "/students/",
        ),
        (
            "Unpublished examination sessions",
            ExamSession.objects.filter(
                academic_year=year, state__in=["approved", "review"]
            ).count(),
            "/examinations/",
        ),
        (
            "Approved invoices not issued",
            Invoice.objects.filter(academic_year=year, state="approved").count(),
            "/finance/",
        ),
        (
            "Overdue library loans",
            Loan.objects.filter(state="issued", due_at__lt=timezone.now()).count(),
            "/library/",
        ),
        (
            "Pending certificate requests",
            DocumentRequest.objects.filter(state__in=["requested", "draft", "approved"]).count(),
            "/certificates/",
        ),
        (
            "Expired staff qualifications",
            Qualification.objects.filter(expires_on__lt=today).count(),
            "/hr/",
        ),
        (
            "Training certificates expired",
            TrainingRecord.objects.filter(certificate_expires_on__lt=today).count(),
            "/hr/",
        ),
        (
            "Transport maintenance due",
            VehicleRecord.objects.filter(next_due_on__lt=today).count(),
            "/transport/",
        ),
    ]


def reporting_rows(category, academic_year, starts_on, ends_on):
    year, start, end = academic_year, starts_on, ends_on
    if category == "students":
        return [
            (
                row.student.admission_number,
                row.student.name if hasattr(row.student, "name") else str(row.student),
                row.section.school_class.name,
                row.section.name,
                row.started_on,
                row.ended_on or "",
            )
            for row in Enrollment.objects.filter(academic_year=year, started_on__lte=end)
            .filter(Q(ended_on__isnull=True) | Q(ended_on__gte=start))
            .select_related("student", "section__school_class")[:5000]
        ], ["Admission", "Student", "Class", "Section", "Started", "Ended"]
    if category == "library":
        return [
            (
                x.copy.accession_number,
                x.copy.book.title,
                str(x.membership.student or x.membership.employee),
                x.issued_at,
                x.due_at,
                x.state,
            )
            for x in Loan.objects.select_related(
                "copy__book", "membership__student", "membership__employee"
            )[:5000]
        ], ["Accession", "Title", "Borrower", "Issued", "Due", "State"]
    if category == "inventory":
        return [
            (
                x.reference,
                x.item.code,
                x.kind,
                x.quantity,
                x.from_location or "",
                x.to_location or "",
                x.occurred_on,
                x.state,
            )
            for x in StockMovement.objects.filter(occurred_on__range=(start, end)).select_related(
                "item", "from_location", "to_location"
            )[:5000]
        ], ["Reference", "Item", "Kind", "Quantity", "From", "To", "Date", "State"]
    if category == "certificates":
        return [
            (x.document_type.name, str(x.student or x.employee), x.state, x.created_at.date())
            for x in DocumentRequest.objects.select_related("document_type", "student", "employee")[
                :5000
            ]
        ], ["Type", "Subject", "State", "Requested"]
    return [], []
