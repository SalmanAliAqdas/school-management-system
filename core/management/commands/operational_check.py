from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from finance.ledger import assert_consistent
from inventory.models import Item, Location
from inventory.services import balance


class Command(BaseCommand):
    help = "Run private operator readiness and domain-integrity checks without exposing details."

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        executor = MigrationExecutor(connection)
        if executor.migration_plan(executor.loader.graph.leaf_nodes()):
            raise CommandError("Pending database migrations detected.")
        assert_consistent()
        negative = [
            (item.pk, location.pk)
            for item in Item.objects.all()
            for location in Location.objects.all()
            if balance(item, location) < 0
        ]
        if negative:
            raise CommandError("Inventory integrity check failed.")
        self.stdout.write(
            self.style.SUCCESS("Database, migrations, ledger and stock checks passed.")
        )
