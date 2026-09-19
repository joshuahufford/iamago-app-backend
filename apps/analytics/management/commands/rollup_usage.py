"""Aggregate raw events into DailyStat rows.

Run it nightly (or after a backfill). Idempotent: re-running a day recomputes
that day's row rather than adding to it.
"""

from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.db.models import Count, Q, Sum

from apps.analytics.models import DailyStat, PractitionerEvent, SearchQuota
from apps.directory.models import RecommendationRequest


class Command(BaseCommand):
    help = "Recompute DailyStat rows from the raw event tables."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=7,
            help="How many days back to recompute, ending today (default 7).",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Recompute every day that has any recorded activity.",
        )

    def handle(self, *args, **options):
        days = self._days_to_process(options)
        for day in days:
            self._rollup(day)

        self.stdout.write(self.style.SUCCESS(f"Rolled up {len(days)} day(s) of usage."))

    def _days_to_process(self, options) -> list[date]:
        if options["all"]:
            seen = set(
                RecommendationRequest.objects.dates("created_at", "day", order="ASC")
            )
            seen |= set(PractitionerEvent.objects.dates("created_at", "day", order="ASC"))
            return sorted(seen)

        today = date.today()
        return [
            today - timedelta(days=offset)
            for offset in range(options["days"] - 1, -1, -1)
        ]

    def _rollup(self, day: date) -> None:
        requests = RecommendationRequest.objects.filter(created_at__date=day)
        search_totals = requests.aggregate(
            searches=Count("id"),
            zero_results=Count("id", filter=Q(result_count=0)),
            with_email=Count("id", filter=~Q(email="")),
            visitors=Count("ip_hash", distinct=True),
            served=Sum("result_count"),
        )

        events = PractitionerEvent.objects.filter(created_at__date=day)
        event_totals = events.aggregate(
            impressions=Count("id", filter=Q(kind=PractitionerEvent.Kind.IMPRESSION)),
            clicks=Count("id", filter=~Q(kind=PractitionerEvent.Kind.IMPRESSION)),
        )

        blocked = (
            SearchQuota.objects.filter(day=day).aggregate(total=Sum("blocked_count"))[
                "total"
            ]
            or 0
        )

        DailyStat.objects.update_or_create(
            day=day,
            defaults={
                "searches": search_totals["searches"] or 0,
                "zero_result_searches": search_totals["zero_results"] or 0,
                "unique_visitors": search_totals["visitors"] or 0,
                "emails_captured": search_totals["with_email"] or 0,
                "recommendations_served": search_totals["served"] or 0,
                "practitioner_impressions": event_totals["impressions"] or 0,
                "practitioner_clicks": event_totals["clicks"] or 0,
                "blocked_requests": blocked,
            },
        )
