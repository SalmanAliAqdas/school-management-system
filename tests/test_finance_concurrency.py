"""Real concurrent PostgreSQL transactions, independent connections and commit checks."""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection, connections, transaction
from django.test import TransactionTestCase

from accounts.models import User
from finance.approvals import request_action
from finance.billing import generate_invoices
from finance.common import control
from finance.ledger import assert_consistent
from finance.models import CreditLot, Invoice, JournalEntry, Payment
from finance.payments import collect_payment

from .test_finance import DAY, FinanceFixture


class FinanceConcurrencyTests(FinanceFixture, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.setUpTestData()

    def race(self, operation):
        barrier = threading.Barrier(2)

        def worker(index):
            try:
                actor = User.objects.get(pk=self.accountant.pk)
                barrier.wait(timeout=10)
                result = operation(actor, index)
                return ("ok", str(result.pk) if hasattr(result, "pk") else result)
            except ValidationError:
                return ("blocked", None)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker, index) for index in range(2)]
            return [future.result(timeout=30) for future in futures]

    def test_concurrent_duplicate_payment_posts_once(self):
        token = uuid.uuid4()
        result = self.race(
            lambda actor, index: collect_payment(
                actor,
                student=self.student,
                value="1000",
                day=DAY,
                method=self.method,
                reference="concurrent-same-reference",
                idempotency_key=token,
            )
        )
        self.assertEqual([row[0] for row in result], ["ok", "ok"])
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(CreditLot.objects.count(), 1)
        self.assertTrue(assert_consistent()["balanced"])

    def test_concurrent_refund_reservations_do_not_overspend(self):
        payment = self.payment("3000")
        result = self.race(
            lambda actor, index: request_action(
                actor,
                "refund_credit",
                credit=payment.credit_lot,
                amount_value="2000",
                day=DAY,
                target_account=control("cash"),
                reason="Concurrent fictional credit refund request",
            )
        )
        self.assertEqual(sorted(row[0] for row in result), ["blocked", "ok"])

    def test_concurrent_generation_single_original(self):
        result = self.race(
            lambda actor, index: generate_invoices(actor, self.cycle.pk, [self.student])
        )
        self.assertEqual([row[0] for row in result], ["ok", "ok"])
        self.assertEqual(Invoice.objects.count(), 1)

    def test_incomplete_journal_rejected_at_commit(self):
        with self.assertRaises(DatabaseError), transaction.atomic():
            JournalEntry.objects.create(
                source_key="incomplete",
                source_type="test",
                source_id="incomplete",
                occurred_on=DAY,
                period=self.period,
                currency=self.settings.currency,
                memo="Incomplete posting cannot commit",
                actor=self.accountant,
            )
        self.assertFalse(JournalEntry.objects.exists())

    def test_finance_migrations_preserve_invoice_payment_and_guards(self):
        from django.db.migrations.executor import MigrationExecutor

        invoice = self.invoice()
        payment = self.payment("1000", invoice)
        snapshot = payment.snapshot
        executor = MigrationExecutor(connection)
        leaves = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate([("finance", "0002_assignment_scope")])
        finally:
            MigrationExecutor(connection).migrate(leaves)
        payment.refresh_from_db()
        self.assertEqual(payment.snapshot, snapshot)
        self.assertEqual(Invoice.objects.get(pk=invoice.pk).total, 10000)
        self.assertTrue(assert_consistent()["balanced"])
        with self.assertRaises(DatabaseError), transaction.atomic():
            Payment.objects.filter(pk=payment.pk).update(amount=1)

    def test_refund_and_allocation_race_preserves_available_credit(self):
        from finance.payments import allocate_credit

        invoice = self.invoice()
        payment = self.payment("3000")

        def operation(actor, index):
            if index:
                return request_action(
                    actor,
                    "refund_credit",
                    credit=payment.credit_lot,
                    amount_value="2000",
                    day=DAY,
                    target_account=control("cash"),
                    reason="Concurrent refund versus allocation",
                )
            return allocate_credit(
                actor, payment.credit_lot.pk, invoice.pk, "2000", DAY, idempotency_key=uuid.uuid4()
            )

        result = self.race(operation)
        self.assertEqual(sorted(row[0] for row in result), ["blocked", "ok"])
        self.assertTrue(assert_consistent()["balanced"])
