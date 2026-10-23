"""Reviewable scheduler entry point: generates drafts, never approves or collects money."""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from finance.billing import BillingContext, calculate_charges, generate_invoices
from finance.common import config, require
from finance.models import BillingCycle
from finance.notifications import send_reminders
from people.models import Student


class Command(BaseCommand):
    help = (
        "Preview scheduled draft billing; use --confirm to create drafts under an authorized actor."
    )

    def add_arguments(self, parser):
        parser.add_argument("--actor", required=True)
        parser.add_argument("--cycle", required=True)
        parser.add_argument("--class-id", type=int)
        parser.add_argument("--confirm", action="store_true")
        parser.add_argument("--reminders", action="store_true")

    def handle(self, *args, **options):
        try:
            actor = get_user_model().objects.get(username=options["actor"], is_active=True)
            require(actor, "generate_invoices")
            cycle = BillingCycle.objects.select_related("academic_year").get(pk=options["cycle"])
            students = (
                Student.objects.filter(enrollments__academic_year=cycle.academic_year)
                .distinct()
                .order_by("pk")
            )
            if options["class_id"]:
                students = students.filter(
                    enrollments__section__school_class_id=options["class_id"]
                ).distinct()
            count = students.count()
            generated = skipped = failed = 0
            for offset in range(0, count, 200):
                batch = list(students[offset : offset + 200])
                if options["confirm"]:
                    outcome = generate_invoices(actor, cycle.pk, batch)
                    generated += len(outcome["generated"])
                    skipped += len(outcome["skipped"])
                    failed += len(outcome["failed"])
                else:
                    context = BillingContext(cycle, batch)
                    for student in batch:
                        try:
                            rows = calculate_charges(student, cycle, config(), context)
                        except ValidationError:
                            failed += 1
                        else:
                            generated += bool(rows)
                            skipped += not bool(rows)
            if options["reminders"] and options["confirm"]:
                send_reminders(actor)
        except (
            get_user_model().DoesNotExist,
            BillingCycle.DoesNotExist,
            ValidationError,
            ValueError,
        ) as exc:
            raise CommandError(
                "Invalid actor, cycle or finance policy; no unauthorized action was executed."
            ) from exc
        self.stdout.write(
            f"{'Created drafts' if options['confirm'] else 'Preview eligible'}: {generated}; "
            f"skipped: {skipped}; failed: {failed}."
        )
        if failed:
            raise CommandError(
                "Some students failed validation; review configuration before retrying."
            )
