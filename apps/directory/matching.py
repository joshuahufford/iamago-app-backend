"""Ranking engine behind the patient-facing recommendation flow.

The brief is deliberately narrow: return *at most three* practitioners, and be
able to explain each one. Scores are therefore built from a handful of
independently meaningful components rather than a single opaque number, and
every component that fires also contributes a human-readable reason.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Q, QuerySet

from apps.directory.models import Practitioner

MAX_RESULTS = 3

# Component ceilings. They sum to 100 before the tier boost, which keeps raw
# scores readable in the admin and in tests.
CONCERN_WEIGHT = 40.0
MODALITY_WEIGHT = 30.0
DISTANCE_WEIGHT = 20.0
AVAILABILITY_WEIGHT = 5.0
TELEHEALTH_WEIGHT = 5.0

# Tier boosts are additive and deliberately smaller than the concern weight, so
# a paying partner can never outrank a materially better clinical match.
TIER_BOOST = {
    Practitioner.Tier.PARTNER: 12.0,
    Practitioner.Tier.VERIFIED: 6.0,
    Practitioner.Tier.STANDARD: 0.0,
}

EARTH_RADIUS_MILES = 3958.7613


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in miles."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


@dataclass
class MatchCriteria:
    """Everything the quiz collected, normalised for the scorer."""

    concern_ids: set = field(default_factory=set)
    modality_ids: set = field(default_factory=set)
    latitude: float | None = None
    longitude: float | None = None
    radius_miles: float = 25.0
    include_telehealth: bool = True
    accepting_new_patients_only: bool = False

    @property
    def has_location(self) -> bool:
        return self.latitude is not None and self.longitude is not None


@dataclass
class ScoredPractitioner:
    practitioner: Practitioner
    score: float
    distance_miles: float | None
    reasons: list[str]


def _as_float(value: Decimal | float | None) -> float | None:
    return None if value is None else float(value)


def _bounding_box(lat: float, lon: float, radius_miles: float):
    """Cheap pre-filter box around a point.

    Narrowing in SQL before the precise haversine pass keeps the Python-side
    work proportional to nearby practitioners rather than the whole table.
    """
    lat_delta = radius_miles / 68.703
    # Longitude degrees shrink toward the poles; guard against cos -> 0.
    cos_lat = max(math.cos(math.radians(lat)), 0.01)
    lon_delta = radius_miles / (69.172 * cos_lat)
    return lat - lat_delta, lat + lat_delta, lon - lon_delta, lon + lon_delta


def candidate_queryset(criteria: MatchCriteria) -> QuerySet[Practitioner]:
    """Published practitioners plausibly relevant to the criteria.

    Geography is applied here as a bounding box; the exact radius test happens
    during scoring. Telehealth providers bypass the box entirely when the
    patient is open to remote care, since distance does not apply to them.
    """
    queryset = Practitioner.objects.filter(is_published=True)

    if criteria.accepting_new_patients_only:
        queryset = queryset.filter(accepting_new_patients=True)

    if criteria.has_location:
        min_lat, max_lat, min_lon, max_lon = _bounding_box(
            criteria.latitude, criteria.longitude, criteria.radius_miles
        )
        nearby = Q(
            latitude__gte=min_lat,
            latitude__lte=max_lat,
            longitude__gte=min_lon,
            longitude__lte=max_lon,
        )
        if criteria.include_telehealth:
            queryset = queryset.filter(nearby | Q(offers_telehealth=True))
        else:
            queryset = queryset.filter(nearby)
    elif not criteria.include_telehealth:
        # No location and no telehealth leaves nothing meaningful to rank on,
        # but the caller may still want the unfiltered set.
        pass

    return queryset.prefetch_related("modalities", "concerns").distinct()


def score_practitioner(
    practitioner: Practitioner, criteria: MatchCriteria
) -> ScoredPractitioner | None:
    """Score one practitioner, or return None if they fail a hard filter."""
    reasons: list[str] = []
    score = 0.0

    practitioner_concerns = {c.id for c in practitioner.concerns.all()}
    practitioner_modalities = {m.id for m in practitioner.modalities.all()}

    # --- Concerns: the strongest signal, scaled by how much overlap there is.
    if criteria.concern_ids:
        matched = criteria.concern_ids & practitioner_concerns
        if matched:
            share = len(matched) / len(criteria.concern_ids)
            score += CONCERN_WEIGHT * share
            reasons.append(
                f"Treats {len(matched)} of your {len(criteria.concern_ids)} "
                f"{'concern' if len(criteria.concern_ids) == 1 else 'concerns'}"
            )

    # --- Modalities: an explicit preference, or inferred from the concerns.
    if criteria.modality_ids:
        matched = criteria.modality_ids & practitioner_modalities
        if matched:
            share = len(matched) / len(criteria.modality_ids)
            score += MODALITY_WEIGHT * share
            names = [m.name for m in practitioner.modalities.all() if m.id in matched]
            reasons.append(f"Offers {', '.join(sorted(names))}")
    elif criteria.concern_ids:
        # No stated preference: reward practising a modality commonly used for
        # the selected concerns, so results stay relevant without a preference.
        implied = _implied_modality_ids(criteria.concern_ids)
        matched = implied & practitioner_modalities
        if matched:
            score += MODALITY_WEIGHT * min(len(matched) / max(len(implied), 1), 1.0)

    # --- Distance: full marks at the doorstep, decaying to zero at the radius.
    distance_miles = None
    lat, lon = _as_float(practitioner.latitude), _as_float(practitioner.longitude)
    if criteria.has_location and lat is not None and lon is not None:
        distance_miles = haversine_miles(criteria.latitude, criteria.longitude, lat, lon)
        if distance_miles <= criteria.radius_miles:
            proximity = 1 - (distance_miles / criteria.radius_miles)
            score += DISTANCE_WEIGHT * proximity
            reasons.append(f"{distance_miles:.1f} mi away")
        elif practitioner.offers_telehealth and criteria.include_telehealth:
            reasons.append("Available by telehealth")
        else:
            # Outside the radius and no remote option: not a real candidate.
            return None
    elif practitioner.offers_telehealth and criteria.include_telehealth:
        reasons.append("Available by telehealth")
    elif criteria.has_location:
        # Has no coordinates and cannot see patients remotely.
        return None

    if practitioner.offers_telehealth and criteria.include_telehealth:
        score += TELEHEALTH_WEIGHT

    if practitioner.accepting_new_patients:
        score += AVAILABILITY_WEIGHT
        reasons.append("Accepting new patients")

    score += TIER_BOOST.get(practitioner.tier, 0.0)
    if practitioner.tier == Practitioner.Tier.PARTNER:
        reasons.append("iamago partner")
    elif practitioner.tier == Practitioner.Tier.VERIFIED:
        reasons.append("Credentials verified by iamago")

    return ScoredPractitioner(
        practitioner=practitioner,
        score=round(score, 2),
        distance_miles=round(distance_miles, 2) if distance_miles is not None else None,
        reasons=reasons,
    )


def _implied_modality_ids(concern_ids: set) -> set:
    from apps.directory.models import HealthConcern

    return set(
        HealthConcern.objects.filter(id__in=concern_ids)
        .values_list("modalities__id", flat=True)
        .exclude(modalities__id=None)
    )


def recommend(criteria: MatchCriteria, limit: int = MAX_RESULTS):
    """Return at most ``limit`` scored practitioners, best first.

    Ties break toward the nearer practitioner and then toward a stable name
    order, so repeated runs of the same quiz produce the same list.
    """
    scored = [
        result
        for result in (
            score_practitioner(practitioner, criteria)
            for practitioner in candidate_queryset(criteria)
        )
        if result is not None
    ]

    scored.sort(
        key=lambda item: (
            -item.score,
            item.distance_miles if item.distance_miles is not None else math.inf,
            item.practitioner.display_name,
        )
    )
    return scored[:limit]
