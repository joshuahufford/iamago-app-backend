from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import User
from apps.common.models import TimeStampedModel
from apps.directory.models import Practitioner, RecommendationRequest


class ContactRequest(TimeStampedModel):
    """A patient asking a practitioner to reach out.

    This is the conversion event the partner tier is actually sold on, so it is
    a first-class record rather than a flag on a search.

    It also carries health information the patient chose to share, which makes
    it the most sensitive row in the system. Consent is captured as the exact
    wording shown at the time — not a boolean — because "they ticked a box"
    is not a defensible record of what someone agreed to.
    """

    class Status(models.TextChoices):
        NEW = "new", _("New")
        VIEWED = "viewed", _("Viewed")
        RESPONDED = "responded", _("Responded")
        CLOSED = "closed", _("Closed")

    practitioner = models.ForeignKey(
        Practitioner, on_delete=models.CASCADE, related_name="contact_requests"
    )
    # Which search produced this, when it came from one.
    recommendation_request = models.ForeignKey(
        RecommendationRequest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contact_requests",
    )
    patient = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contact_requests",
    )

    name = models.CharField(max_length=200)
    email = models.EmailField()
    phone = models.CharField(max_length=40, blank=True)
    message = models.TextField(
        blank=True, help_text=_("What the patient wants help with, in their words.")
    )

    # Consent ------------------------------------------------------------
    share_concerns = models.BooleanField(
        default=False,
        help_text=_("Whether the patient agreed to share their selected concerns."),
    )
    consent_text = models.TextField(
        help_text=_("The exact wording the patient agreed to, stored verbatim.")
    )
    consented_at = models.DateTimeField(default=timezone.now)
    ip_hash = models.CharField(max_length=64, blank=True, db_index=True)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.NEW)
    first_viewed_at = models.DateTimeField(null=True, blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    practitioner_note = models.TextField(blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["practitioner", "status", "created_at"]),
            models.Index(fields=["created_at"]),
        ]
        verbose_name = _("contact request")
        verbose_name_plural = _("contact requests")

    def __str__(self):
        return f"{self.name} → {self.practitioner.display_name}"

    @property
    def shared_concerns(self):
        """Concerns from the originating search, if the patient shared them.

        Returns nothing when consent was withheld, so callers cannot leak the
        health context by forgetting to check the flag.
        """
        if not self.share_concerns or self.recommendation_request_id is None:
            return []
        return list(self.recommendation_request.concerns.all())

    def mark_viewed(self, *, by: User | None = None, ip_hash: str = "") -> None:
        if self.first_viewed_at is None:
            self.first_viewed_at = timezone.now()
            if self.status == self.Status.NEW:
                self.status = self.Status.VIEWED
            self.save(update_fields=["first_viewed_at", "status", "updated_at"])

        ContactRequestAccess.objects.create(
            contact_request=self, actor=by, ip_hash=ip_hash
        )


class ContactRequestAccess(models.Model):
    """Audit trail: every time someone opens a contact request.

    A contact request can carry why a person is seeking care, so reading one is
    an event worth being able to account for after the fact. Rows are never
    edited or deleted through the app.
    """

    contact_request = models.ForeignKey(
        ContactRequest, on_delete=models.CASCADE, related_name="accesses"
    )
    actor = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    ip_hash = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = _("contact request access")
        verbose_name_plural = _("contact request accesses")

    def __str__(self):
        actor = self.actor.email if self.actor else "anonymous"
        return f"{actor} viewed {self.contact_request_id} at {self.created_at}"
