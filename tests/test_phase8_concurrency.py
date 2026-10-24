import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from django.core.exceptions import ValidationError
from django.db import DatabaseError, connections
from django.test import TransactionTestCase

from accounts.models import User
from inventory.models import Category as StockCategory
from inventory.models import Item, StockMovement
from inventory.models import Location as StockLocation
from inventory.services import balance, finalize
from library.models import Book, Category, Copy, Location, Membership, Policy
from library.services import issue

from .helpers import make_school_data, make_user


class Phase8ConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.d = make_school_data()
        self.principal = make_user("p8-race-principal", "Principal")
        self.librarian = make_user("p8-race-librarian", "Librarian")

    def race(self, actor, operation):
        barrier = threading.Barrier(2)

        def worker(index):
            try:
                current = User.objects.get(pk=actor.pk)
                barrier.wait(timeout=10)
                return "ok", operation(current, index).pk
            except (ValidationError, DatabaseError):
                return "blocked", None
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker, index) for index in range(2)]
            return [future.result(timeout=30) for future in futures]

    def test_concurrent_stock_issue_never_goes_negative(self):
        category = StockCategory.objects.create(name="Supplies", kind="consumable")
        item = Item.objects.create(category=category, code="RACE", name="Race stock", unit="box")
        location = StockLocation.objects.create(name="Race store")
        opening = StockMovement.objects.create(
            reference="RACE-OPEN",
            item=item,
            kind="opening",
            quantity=10,
            to_location=location,
            occurred_on=date(2026, 10, 1),
            actor=self.principal,
        )
        finalize(self.principal, opening.pk)
        rows = [
            StockMovement.objects.create(
                reference=f"RACE-{index}",
                item=item,
                kind="issue",
                quantity=7,
                from_location=location,
                occurred_on=date(2026, 10, 2),
                actor=self.principal,
            )
            for index in range(2)
        ]
        result = self.race(self.principal, lambda actor, index: finalize(actor, rows[index].pk))
        self.assertEqual(sorted(status for status, _pk in result), ["blocked", "ok"])
        self.assertEqual(balance(item, location), 3)

    def test_concurrent_copy_issue_has_one_winner(self):
        policy = Policy.objects.create(name="Race policy", borrower_kind="student")
        members = [
            Membership.objects.create(student=student, policy=policy)
            for student in (self.d["own"], self.d["other"])
        ]
        category = Category.objects.create(name="Race books")
        location = Location.objects.create(name="Race shelf")
        book = Book.objects.create(title="One Copy", authors="Fictional", category=category)
        copy = Copy.objects.create(book=book, accession_number="RACE-COPY", location=location)
        result = self.race(
            self.librarian,
            lambda actor, index: issue(actor, copy.pk, members[index].pk),
        )
        self.assertEqual(sorted(status for status, _pk in result), ["blocked", "ok"])
        self.assertEqual(copy.loans.filter(state="issued").count(), 1)
