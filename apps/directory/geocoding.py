"""Turning a typed place name into coordinates.

Production uses the Google Geocoding API. When no API key is configured — local
development, CI, and the test suite — we fall back to a small bundled table of
US cities so the whole discovery flow stays exercisable without credentials or
network access. The fallback is explicitly not a substitute for real geocoding;
``GeocodeResult.source`` records which path produced a result.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
REQUEST_TIMEOUT_SECONDS = 5

# A deliberately small set: enough to demo and test the flow, not a dataset to
# depend on. Keys are matched case-insensitively against the query.
FALLBACK_PLACES: dict[str, tuple[str, float, float]] = {
    "austin": ("Austin, TX, USA", 30.2672, -97.7431),
    "atlanta": ("Atlanta, GA, USA", 33.7490, -84.3880),
    "boston": ("Boston, MA, USA", 42.3601, -71.0589),
    "boulder": ("Boulder, CO, USA", 40.0150, -105.2705),
    "charlotte": ("Charlotte, NC, USA", 35.2271, -80.8431),
    "chicago": ("Chicago, IL, USA", 41.8781, -87.6298),
    "dallas": ("Dallas, TX, USA", 32.7767, -96.7970),
    "denver": ("Denver, CO, USA", 39.7392, -104.9903),
    "houston": ("Houston, TX, USA", 29.7604, -95.3698),
    "los angeles": ("Los Angeles, CA, USA", 34.0522, -118.2437),
    "miami": ("Miami, FL, USA", 25.7617, -80.1918),
    "minneapolis": ("Minneapolis, MN, USA", 44.9778, -93.2650),
    "nashville": ("Nashville, TN, USA", 36.1627, -86.7816),
    "new york": ("New York, NY, USA", 40.7128, -74.0060),
    "philadelphia": ("Philadelphia, PA, USA", 39.9526, -75.1652),
    "phoenix": ("Phoenix, AZ, USA", 33.4484, -112.0740),
    "portland": ("Portland, OR, USA", 45.5152, -122.6784),
    "raleigh": ("Raleigh, NC, USA", 35.7796, -78.6382),
    "san diego": ("San Diego, CA, USA", 32.7157, -117.1611),
    "san francisco": ("San Francisco, CA, USA", 37.7749, -122.4194),
    "seattle": ("Seattle, WA, USA", 47.6062, -122.3321),
    "washington": ("Washington, DC, USA", 38.9072, -77.0369),
}


@dataclass
class GeocodeResult:
    label: str
    latitude: float
    longitude: float
    source: str  # "google" or "fallback"


def geocode(query: str) -> GeocodeResult | None:
    """Resolve a free-text place to coordinates, or None if not found."""
    query = (query or "").strip()
    if not query:
        return None

    api_key = getattr(settings, "GOOGLE_MAPS_API_KEY", "")
    if api_key:
        result = _geocode_google(query, api_key)
        if result is not None:
            return result
        # Fall through: a Google miss or outage should not break the flow.

    return _geocode_fallback(query)


def _geocode_google(query: str, api_key: str) -> GeocodeResult | None:
    try:
        response = requests.get(
            GOOGLE_GEOCODE_URL,
            params={"address": query, "key": api_key},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        logger.warning("Google geocoding failed for %r", query, exc_info=True)
        return None

    if payload.get("status") != "OK" or not payload.get("results"):
        return None

    best = payload["results"][0]
    location = best["geometry"]["location"]
    return GeocodeResult(
        label=best.get("formatted_address", query),
        latitude=float(location["lat"]),
        longitude=float(location["lng"]),
        source="google",
    )


def _geocode_fallback(query: str) -> GeocodeResult | None:
    needle = query.strip().lower()

    # Exact key first, then the longest key contained in the query, so that
    # "Portland, OR" beats a stray substring match.
    if needle in FALLBACK_PLACES:
        label, lat, lon = FALLBACK_PLACES[needle]
        return GeocodeResult(label, lat, lon, source="fallback")

    matches = [key for key in FALLBACK_PLACES if key in needle]
    if not matches:
        return None

    label, lat, lon = FALLBACK_PLACES[max(matches, key=len)]
    return GeocodeResult(label, lat, lon, source="fallback")
