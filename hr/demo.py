from datetime import time
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction

from attendance.calendar import school_now
from certificates.models import DocumentRequest, DocumentType, Signatory
from certificates.services import create_request, decide, issue
from finance.common import control
from finance.models import FinancialPeriod
from inventory.models import Asset, AssetEvent, Item, StockMovement
from inventory.models import Category as StockCategory
from inventory.models import Location as StockLocation
from inventory.services import finalize
from library.models import Book, Category, Copy, Loan, Location, Membership, Policy
from library.services import issue as issue_book
from payroll.models import Component, PayrollPeriod, PayrollSettings, SalaryRevision
from payroll.services import generate, transition
from people.models import Staff
from transport.models import Route, Stop, StudentAssignment, Trip, Vehicle
from transport.services import assign_student, save_trip

from .models import (
    Department,
    Designation,
    Employee,
    EmploymentRecord,
    LeaveEntitlement,
    LeavePolicy,
)


@transaction.atomic
def seed_phase8_demo(accounts, year, students, sections):
    if not settings.DEBUG or not settings.ALLOW_DEMO_DATA:
        raise ValidationError("Phase 8 demonstrations require explicit local demo mode.")
    now = school_now()
    department, _ = Department.objects.get_or_create(
        name="DEMO School Operations", defaults={"code": "DEMO-OPS"}
    )
    designation, _ = Designation.objects.get_or_create(
        department=department, title="Operations officer"
    )
    staff, _ = Staff.objects.get_or_create(
        employee_number="DEMO-S008",
        defaults={
            "user": accounts["demo.hr"],
            "first_name": "Jordan",
            "last_name": "Ellis",
            "job_title": "HR manager",
            "joined_on": year.starts_on,
        },
    )
    employee, _ = Employee.objects.get_or_create(
        user=accounts["demo.hr"], defaults={"staff": staff, "employee_code": "DEMO-E008"}
    )
    EmploymentRecord.objects.get_or_create(
        employee=employee,
        starts_on=year.starts_on,
        defaults={
            "department": department,
            "designation": designation,
            "employment_type": "permanent",
        },
    )
    policy, _ = LeavePolicy.objects.get_or_create(
        name="DEMO Annual leave",
        defaults={"kind": "annual", "annual_days": 20, "carry_forward_days": 5},
    )
    LeaveEntitlement.objects.get_or_create(
        employee=employee, policy=policy, year=now.year, defaults={"days": 20}
    )

    expense, payable, bank = control("expense"), control("payable"), control("bank")
    PayrollSettings.objects.get_or_create(
        pk=1, defaults={"salary_payable_account": payable, "payment_account": bank}
    )
    component, _ = Component.objects.get_or_create(
        code="DEMO-BASIC",
        defaults={"name": "DEMO Basic salary", "kind": "earning", "account": expense},
    )
    SalaryRevision.objects.get_or_create(
        employee=employee,
        component=component,
        effective_from=year.starts_on,
        defaults={"amount": Decimal("85000"), "authorized_by": accounts["demo.principal"]},
    )
    financial = FinancialPeriod.objects.filter(
        starts_on__lte=now.date(), ends_on__gte=now.date(), is_closed=False
    ).first()
    if financial:
        period, _ = PayrollPeriod.objects.get_or_create(
            name=f"DEMO Payroll {now:%B %Y}",
            defaults={
                "starts_on": max(financial.starts_on, now.date().replace(day=1)),
                "ends_on": min(financial.ends_on, now.date().replace(day=28)),
                "payment_date": now.date(),
            },
        )
        if not hasattr(period, "run"):
            run = generate(accounts["demo.hr"], period, [employee])
            transition(accounts["demo.hr"], run.pk, "submit")
            transition(accounts["demo.principal"], run.pk, "approve")
            transition(accounts["demo.principal"], run.pk, "finalize")

    library_policy, _ = Policy.objects.get_or_create(
        name="DEMO Student borrowing",
        defaults={"borrower_kind": "student", "loan_days": 14, "limit": 3},
    )
    member, _ = Membership.objects.get_or_create(
        student=students[0], defaults={"policy": library_policy}
    )
    category, _ = Category.objects.get_or_create(name="DEMO Fiction")
    location, _ = Location.objects.get_or_create(name="DEMO Main Library", defaults={"shelf": "A1"})
    book, _ = Book.objects.get_or_create(
        title="DEMO The Lantern Garden", authors="Fictional Author", category=category
    )
    copy, _ = Copy.objects.get_or_create(
        accession_number="DEMO-BOOK-001", defaults={"book": book, "location": location}
    )
    if copy.status == "available" and not Loan.objects.filter(copy=copy).exists():
        issue_book(accounts["demo.librarian"], copy.pk, member.pk)

    vehicle, _ = Vehicle.objects.get_or_create(
        identifier="DEMO-BUS-01",
        defaults={"registration": "DEMO-REG-01", "kind": "School bus", "capacity": 24},
    )
    route, _ = Route.objects.get_or_create(name="DEMO North Learning Route")
    pickup, _ = Stop.objects.get_or_create(
        route=route, sequence=1, defaults={"name": "DEMO Garden Stop"}
    )
    school, _ = Stop.objects.get_or_create(
        route=route, sequence=2, defaults={"name": "DEMO School Gate"}
    )
    trip = Trip.objects.filter(route=route, direction="morning").first()
    if not trip:
        trip = Trip(
            route=route,
            direction="morning",
            vehicle=vehicle,
            driver=employee,
            starts_at=time(7),
            ends_at=time(8),
            effective_from=year.starts_on,
        )
        save_trip(accounts["demo.transport"], trip)
    if not StudentAssignment.objects.filter(
        student=students[0], trip=trip, ends_on__isnull=True
    ).exists():
        assign_student(
            accounts["demo.transport"],
            StudentAssignment(
                student=students[0],
                trip=trip,
                pickup_stop=pickup,
                dropoff_stop=school,
                starts_on=year.starts_on,
            ),
        )

    stock_category, _ = StockCategory.objects.get_or_create(
        name="DEMO Stationery", defaults={"kind": "consumable"}
    )
    item, _ = Item.objects.get_or_create(
        code="DEMO-PAPER",
        defaults={
            "category": stock_category,
            "name": "DEMO Exercise paper",
            "unit": "ream",
            "minimum_stock": 5,
        },
    )
    store, _ = StockLocation.objects.get_or_create(name="DEMO Main Store")
    movement, created = StockMovement.objects.get_or_create(
        reference="DEMO-STOCK-OPEN",
        defaults={
            "item": item,
            "kind": "opening",
            "quantity": 25,
            "to_location": store,
            "occurred_on": now.date(),
            "actor": accounts["demo.admin"],
        },
    )
    if created:
        finalize(accounts["demo.admin"], movement.pk)
    asset, created = Asset.objects.get_or_create(
        identifier="DEMO-LAPTOP-001",
        defaults={
            "item": item,
            "acquired_on": now.date(),
            "cost": 100000,
            "location": store,
            "custodian": employee,
        },
    )
    if created:
        AssetEvent.objects.create(
            asset=asset,
            kind="acquired",
            occurred_on=now.date(),
            details="Fictional demonstration asset",
            actor=accounts["demo.admin"],
        )

    kind, _ = DocumentType.objects.get_or_create(
        name="DEMO Enrollment certificate",
        defaults={
            "audience": "student",
            "template_text": (
                "This confirms current enrollment in the fictional demonstration school."
            ),
        },
    )
    signatory, _ = Signatory.objects.get_or_create(name="DEMO Principal", title="Principal")
    if not DocumentRequest.objects.filter(document_type=kind, student=students[0]).exists():
        request = create_request(
            accounts["demo.student"],
            DocumentRequest(
                document_type=kind, student=students[0], purpose="Fictional demonstration"
            ),
        )
        decide(accounts["demo.principal"], request.pk, True)
        issue(accounts["demo.principal"], request.pk, signatory)
