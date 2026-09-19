"""Drop raw usage rows past their retention window.

DailyStat rollups are kept indefinitely — they are small and carry no visitor
identifiers. The raw per-visitor rows are what actually age out.
"""

from datetime import date, timedelta

from django.core.management.base import BaseCommand

from apps.analytics.models import PractitionerEvent, SearchQuota


class Command(BaseCommand):
    help = "Delete raw usage rows older than the retention window."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=90, help="Retention window.")

    def handle(self, *args, **options):
        cutoff = date.today() - timedelta(days=options["days"])

        quotas, _ = SearchQuota.objects.filter(day__lt=cutoff).delete()
        events, _ = PractitionerEvent.objects.filter(created_at__date__lt=cutoff).delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Pruned {quotas} quota row(s) and {events} event(s) before {cutoff}."
            )
        )
