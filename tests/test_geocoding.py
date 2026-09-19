from unittest.mock import Mock, patch

import pytest
import requests

from apps.directory.geocoding import geocode


class TestFallbackGeocoder:
    """Exercised whenever no Google key is configured (dev, CI, tests)."""

    def test_resolves_an_exact_city(self, settings):
        settings.GOOGLE_MAPS_API_KEY = ""

        result = geocode("Denver")

        assert result.label == "Denver, CO, USA"
        assert result.source == "fallback"
        assert result.latitude == pytest.approx(39.7392)

    def test_is_case_insensitive(self, settings):
        settings.GOOGLE_MAPS_API_KEY = ""

        assert geocode("SAN FRANCISCO").label == "San Francisco, CA, USA"

    def test_matches_a_city_inside_a_longer_string(self, settings):
        settings.GOOGLE_MAPS_API_KEY = ""

        assert geocode("Portland, OR 97201").label == "Portland, OR, USA"

    def test_returns_none_for_an_unknown_place(self, settings):
        settings.GOOGLE_MAPS_API_KEY = ""

        assert geocode("Nowheresville") is None

    def test_returns_none_for_blank_input(self, settings):
        settings.GOOGLE_MAPS_API_KEY = ""

        assert geocode("") is None
        assert geocode("   ") is None


class TestGoogleGeocoder:
    def test_uses_google_when_a_key_is_configured(self, settings):
        settings.GOOGLE_MAPS_API_KEY = "test-key"
        response = Mock()
        response.json.return_value = {
            "status": "OK",
            "results": [
                {
                    "formatted_address": "1 Infinite Loop, Cupertino, CA 95014, USA",
                    "geometry": {"location": {"lat": 37.3318, "lng": -122.0312}},
                }
            ],
        }

        with patch("apps.directory.geocoding.requests.get", return_value=response) as get:
            result = geocode("1 Infinite Loop")

        assert result.source == "google"
        assert result.label == "1 Infinite Loop, Cupertino, CA 95014, USA"
        assert result.latitude == pytest.approx(37.3318)
        assert get.call_args.kwargs["params"]["key"] == "test-key"

    def test_falls_back_when_google_errors(self, settings):
        """An outage at Google must not take the discovery flow down."""
        settings.GOOGLE_MAPS_API_KEY = "test-key"

        with patch(
            "apps.directory.geocoding.requests.get",
            side_effect=requests.RequestException("boom"),
        ):
            result = geocode("Denver")

        assert result is not None
        assert result.source == "fallback"

    def test_falls_back_when_google_finds_nothing(self, settings):
        settings.GOOGLE_MAPS_API_KEY = "test-key"
        response = Mock()
        response.json.return_value = {"status": "ZERO_RESULTS", "results": []}

        with patch("apps.directory.geocoding.requests.get", return_value=response):
            result = geocode("Seattle")

        assert result.source == "fallback"
        assert result.label == "Seattle, WA, USA"


@pytest.mark.django_db
class TestGeocodeEndpoint:
    def test_returns_coordinates(self, api, settings):
        settings.GOOGLE_MAPS_API_KEY = ""

        response = api.get("/api/directory/geocode/", {"q": "Boston"})

        assert response.status_code == 200
        assert response.json()["label"] == "Boston, MA, USA"

    def test_unknown_place_is_404(self, api, settings):
        settings.GOOGLE_MAPS_API_KEY = ""

        assert api.get("/api/directory/geocode/", {"q": "zzzz"}).status_code == 404
