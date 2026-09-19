from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import User
from apps.common.models import TimeStampedModel


class Modality(TimeStampedModel):
    """A practice or treatment approach, e.g. Acupuncture or Naturopathy.

    These are what a patient picks when they know the kind of care they want.
    """

    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "name")
        verbose_name_plural = _("modalities")

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class HealthConcern(TimeStampedModel):
    """What a patient is actually trying to solve, e.g. "Chronic fatigue".

    Concerns are the primary input to the quiz because most patients know their
    problem, not the modality that treats it. ``modalities`` records which
    approaches typically address a concern, so we can still rank sensibly when
    a patient expresses no modality preference.
    """

    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    description = models.TextField(blank=True)
    modalities = models.ManyToManyField(Modality, related_name="concerns", blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "name")

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Practitioner(TimeStampedModel):
    """A provider listed in the directory."""

    class Tier(models.TextChoices):
        STANDARD = "standard", _("Standard")
        # Vetted by us but not paying: earns a trust badge and a small boost.
        VERIFIED = "verified", _("Verified")
        # Paying partner: earns a badge and the strongest boost.
        PARTNER = "partner", _("Partner")

    # Set once a practitioner claims their listing (portal login, phase 2).
    user = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="practitioner",
    )

    display_name = models.CharField(max_length=200)
    credentials = models.CharField(
        max_length=120, blank=True, help_text=_("e.g. LAc, ND, DC, MD")
    )
    practice_name = models.CharField(max_length=200, blank=True)
    bio = models.TextField(blank=True)
    photo_url = models.URLField(blank=True)
    website = models.URLField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    years_experience = models.PositiveSmallIntegerField(null=True, blank=True)

    modalities = models.ManyToManyField(
        Modality, related_name="practitioners", blank=True
    )
    concerns = models.ManyToManyField(
        HealthConcern, related_name="practitioners", blank=True
    )

    address_line1 = models.CharField(max_length=200, blank=True)
    address_line2 = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=120, blank=True)
    region = models.CharField(max_length=120, blank=True, help_text=_("State/province"))
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=2, default="US")

    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )

    offers_telehealth = models.BooleanField(default=False)
    accepting_new_patients = models.BooleanField(default=True)
    accepts_insurance = models.BooleanField(default=False)

    tier = models.CharField(max_length=10, choices=Tier.choices, default=Tier.STANDARD)
    is_published = models.BooleanField(
        default=False, help_text=_("Only published practitioners can be recommended.")
    )

    class Meta:
        ordering = ("display_name",)
        indexes = [
            models.Index(fields=["is_published", "tier"]),
            models.Index(fields=["latitude", "longitude"]),
        ]

    def __str__(self):
        return f"{self.display_name}{f', {self.credentials}' if self.credentials else ''}"

    @property
    def is_preferred(self) -> bool:
        """Whether the listing earns a badge (either tier above standard)."""
        return self.tier in (self.Tier.PARTNER, self.Tier.VERIFIED)

    @property
    def has_location(self) -> bool:
        return self.latitude is not None and self.longitude is not None


class RecommendationRequest(TimeStampedModel):
    """One run of the patient-facing quiz, kept so it can be revisited.

    Anonymous runs are allowed — the homepage is deliberately not behind a
    login wall — so ``user`` is nullable and ``claim_token`` lets a visitor
    attach the run to an account they create later.
    """

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="recommendation_requests",
    )
    claim_token = models.CharField(max_length=64, db_index=True, blank=True)

    concerns = models.ManyToManyField(HealthConcern, blank=True)
    modalities = models.ManyToManyField(Modality, blank=True)

    location_label = models.CharField(max_length=255, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    radius_km = models.PositiveSmallIntegerField(default=40)

    include_telehealth = models.BooleanField(default=True)
    accepting_new_patients_only = models.BooleanField(default=False)

    def __str__(self):
        return f"Request {self.id} ({self.location_label or 'no location'})"


class Recommendation(TimeStampedModel):
    """A single practitioner returned for a request, with its reasoning."""

    request = models.ForeignKey(
        RecommendationRequest, on_delete=models.CASCADE, related_name="recommendations"
    )
    practitioner = models.ForeignKey(
        Practitioner, on_delete=models.CASCADE, related_name="recommendations"
    )
    rank = models.PositiveSmallIntegerField()
    score = models.FloatField()
    distance_km = models.FloatField(null=True, blank=True)
    # Short human-readable strings shown on the result card ("Treats 2 of your
    # 3 concerns"), so the ranking is explainable rather than a black box.
    reasons = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ("rank",)
        constraints = [
            models.UniqueConstraint(
                fields=["request", "practitioner"], name="unique_practitioner_per_request"
            ),
        ]

    def __str__(self):
        return f"#{self.rank} {self.practitioner.display_name}"
