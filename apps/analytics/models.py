from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import TimeStampedModel
from apps.directory.models import Practitioner, RecommendationRequest


class SearchQuota(models.Model):
    """Per-visitor, per-day search counter backing the anti-scraping limit.

    Keyed on a salted hash rather than the raw address: the directory is the
    asset worth protecting, and we do not need to know who anyone is to protect
    it. Rows are disposable — ``prune_usage`` clears old ones.
    """

    ip_hash = models.CharField(max_length=64, db_index=True)
    day = models.DateField(db_index=True)
    search_count = models.PositiveIntegerField(default=0)
    # Recorded so we can see whether the email gate is doing anything.
    gave_email = models.BooleanField(default=False)
    blocked_count = models.PositiveIntegerField(default=0)
    # Contact requests are counted separately from searches: a patient who
    # searched a lot should still be able to enquire, and an enquiry is far
    # more costly to a practitioner than a search is to us.
    contact_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["ip_hash", "day"], name="unique_quota_per_day"
            )
        ]
        ordering = ("-day",)
        verbose_name = _("search quota")
        verbose_name_plural = _("search quotas")

    def __str__(self):
        return f"{self.ip_hash[:12]}… {self.day}: {self.search_count}"


class PractitionerEvent(TimeStampedModel):
    """An impression or click-through on a practitioner listing.

    Impressions are written server-side when a recommendation is produced, so
    they cannot be inflated by a client. Clicks are reported by the browser,
    which is the only place that knows about them.
    """

    class Kind(models.TextChoices):
        IMPRESSION = "impression", _("Recommended")
        PROFILE = "profile", _("Profile opened")
        PHONE = "phone", _("Phone revealed")
        WEBSITE = "website", _("Website opened")

    practitioner = models.ForeignKey(
        Practitioner, on_delete=models.CASCADE, related_name="events"
    )
    request = models.ForeignKey(
        RecommendationRequest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="practitioner_events",
    )
    kind = models.CharField(max_length=12, choices=Kind.choices, db_index=True)
    # Denormalised so partner reporting stays honest even if a tier changes.
    tier_at_event = models.CharField(max_length=10, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["practitioner", "kind", "created_at"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.get_kind_display()}: {self.practitioner_id}"


class DailyStat(models.Model):
    """Pre-aggregated counts, so the dashboard never scans the event tables."""

    day = models.DateField(unique=True)

    searches = models.PositiveIntegerField(default=0)
    zero_result_searches = models.PositiveIntegerField(
        default=0, help_text=_("Searches that matched nobody — your coverage gaps.")
    )
    unique_visitors = models.PositiveIntegerField(default=0)
    emails_captured = models.PositiveIntegerField(default=0)
    recommendations_served = models.PositiveIntegerField(default=0)

    practitioner_impressions = models.PositiveIntegerField(default=0)
    practitioner_clicks = models.PositiveIntegerField(default=0)

    blocked_requests = models.PositiveIntegerField(
        default=0, help_text=_("Searches refused by the rate limit.")
    )

    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-day",)
        verbose_name = _("daily usage")
        verbose_name_plural = _("daily usage")

    def __str__(self):
        return f"{self.day}: {self.searches} searches"

    @property
    def click_through_rate(self) -> float:
        if not self.practitioner_impressions:
            return 0.0
        return self.practitioner_clicks / self.practitioner_impressions
