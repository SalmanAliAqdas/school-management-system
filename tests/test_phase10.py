import uuid
from datetime import date
from decimal import Decimal

from django.test import TestCase

from analytics.selectors import _collections
from certificates.models import DocumentRequest, DocumentType, IssuedDocument, Signatory
from finance.models import Account, FinancialRequest, Payment, PaymentMethod

from .helpers import make_school_data, make_user


class Phase10AuditRegressionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.data = make_school_data()
        cls.cashier = make_user("phase10-cashier", "Accountant")
        cls.reviewer = make_user("phase10-principal", "Principal")
        account = Account.objects.create(
            code="P10-CASH", name="Phase 10 cash", kind="asset", control="cash"
        )
        cls.method = PaymentMethod.objects.create(name="Phase 10 cash", account=account)

    def payment(self, reference, amount, paid_on):
        return Payment.objects.create(
            idempotency_key=uuid.uuid4(),
            fingerprint=reference,
            number=reference,
            student=self.data["own"],
            paid_on=paid_on,
            amount=amount,
            method=self.method,
            reference=reference,
            state="posted",
            created_by=self.cashier,
            posted_by=self.reviewer,
        )

    def reverse(self, payment, occurred_on):
        return FinancialRequest.objects.create(
            kind="reverse_payment",
            student=payment.student,
            payment=payment,
            amount=payment.amount,
            occurred_on=occurred_on,
            reason="Phase 10 reversal regression",
            requested_by=self.cashier,
            state="approved",
            reviewed_by=self.reviewer,
            reviewed_at=payment.created_at,
            decision_reason="Independently reviewed for regression coverage",
        )

    def test_collections_use_one_query_and_respect_reversal_cutoff(self):
        included = self.payment("P10-001", Decimal("125.00"), date(2026, 10, 1))
        reversed_in_window = self.payment("P10-002", Decimal("50.00"), date(2026, 10, 2))
        reversed_after_window = self.payment("P10-003", Decimal("25.00"), date(2026, 10, 3))
        self.reverse(reversed_in_window, date(2026, 10, 4))
        self.reverse(reversed_after_window, date(2026, 11, 1))

        with self.assertNumQueries(1):
            total = _collections(date(2026, 10, 1), date(2026, 10, 31))

        self.assertEqual(total, included.amount + reversed_after_window.amount)

    def test_public_certificate_verification_is_not_cacheable(self):
        document_type = DocumentType.objects.create(
            name="Phase 10 enrollment statement",
            audience="student",
            template_text="Enrollment confirmed.",
        )
        signatory = Signatory.objects.create(name="Fictional Principal", title="Principal")
        request = DocumentRequest.objects.create(
            document_type=document_type,
            student=self.data["own"],
            requested_by=self.data["student_user"],
            purpose="Phase 10 cache regression",
            state="issued",
        )
        document = IssuedDocument.objects.create(
            request=request,
            number="P10-CERT-001",
            issued_at=request.created_at,
            issued_by=self.reviewer,
            signatory=signatory,
            snapshot={"type": document_type.name},
        )

        response = self.client.get(f"/certificates/verify/{document.verification_token}/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
