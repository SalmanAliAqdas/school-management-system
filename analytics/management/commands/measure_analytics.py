import json
import time

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.test.utils import CaptureQueriesContext

from academics.models import AcademicYear
from analytics.selectors import executive_metrics


class Command(BaseCommand):
    help = "Measure executive analytics on saved fictional/local records without modifying data."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)

    def handle(self, *args, **options):
        actor = (
            get_user_model().objects.filter(username=options["username"], is_active=True).first()
        )
        year = AcademicYear.objects.filter(is_current=True).first()
        if not actor or not year or not actor.has_perm("core.view_executive_analytics"):
            raise CommandError("Choose an active authorized user and current academic year.")
        started = time.perf_counter()
        with CaptureQueriesContext(connection) as queries:
            result = executive_metrics(actor, year, year.starts_on, year.ends_on)
        elapsed = (time.perf_counter() - started) * 1000
        self.stdout.write(
            json.dumps(
                {
                    "duration_ms": round(elapsed, 3),
                    "queries": len(queries),
                    "active_students": result["active_students"],
                    "year": year.name,
                }
            )
        )
