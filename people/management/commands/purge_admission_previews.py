from django.core.management.base import BaseCommand
from django.utils import timezone

from people.models import AdmissionImport


class Command(BaseCommand):
    help = "Clear personal row data from expired, unconfirmed CSV previews; keep batch audit IDs."

    def handle(self, *args, **options):
        count = (
            AdmissionImport.objects.filter(
                expires_at__lte=timezone.now(), confirmed_at__isnull=True
            )
            .exclude(rows=[])
            .update(rows=[])
        )
        self.stdout.write(f"Cleared {count} expired admission previews.")
