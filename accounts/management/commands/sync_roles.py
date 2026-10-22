from django.core.management.base import BaseCommand

from accounts.roles import sync_roles


class Command(BaseCommand):
    help = "Create or synchronize SchoolOS's managed permission groups."

    def handle(self, *args, **options):
        sync_roles()
        self.stdout.write(self.style.SUCCESS("SchoolOS roles synchronized."))
