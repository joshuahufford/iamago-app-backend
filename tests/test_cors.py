"""CORS is what lets the deployed frontend talk to this API at all, and an
over-broad rule is what lets anyone else do the same. Both directions matter.
"""

import pytest
from django.urls import reverse

PREVIEW_REGEX = r"^https://iamago-app-frontend-[a-z0-9-]+\.vercel\.app$"


def allowed(response) -> bool:
    return bool(response.headers.get("access-control-allow-origin"))


@pytest.mark.django_db
class TestCors:
    def test_a_listed_origin_is_allowed(self, api, settings):
        settings.CORS_ALLOWED_ORIGINS = ["https://iamago.com"]

        response = api.get(reverse("concern-list"), HTTP_ORIGIN="https://iamago.com")

        assert allowed(response)

    def test_an_unlisted_origin_is_not(self, api, settings):
        settings.CORS_ALLOWED_ORIGINS = ["https://iamago.com"]

        response = api.get(
            reverse("concern-list"), HTTP_ORIGIN="https://evil.example.com"
        )

        assert not allowed(response)

    def test_a_preview_deployment_is_allowed_by_regex(self, api, settings):
        """Preview builds get a fresh hostname each time, so they can never be
        listed individually."""
        settings.CORS_ALLOWED_ORIGINS = ["https://iamago.com"]
        settings.CORS_ALLOWED_ORIGIN_REGEXES = [PREVIEW_REGEX]

        response = api.get(
            reverse("concern-list"),
            HTTP_ORIGIN="https://iamago-app-frontend-h7x2k9-josh.vercel.app",
        )

        assert allowed(response)

    def test_the_preview_pattern_is_anchored_to_the_real_host(self, api, settings):
        """An unanchored pattern would match any domain that merely contains
        the prefix, which is how this kind of rule usually goes wrong."""
        settings.CORS_ALLOWED_ORIGINS = []
        settings.CORS_ALLOWED_ORIGIN_REGEXES = [PREVIEW_REGEX]

        for impostor in (
            "https://iamago-app-frontend-evil.attacker.com",
            "http://iamago-app-frontend-x.vercel.app",
            "https://iamago-app-frontend-x.vercel.app.attacker.com",
        ):
            response = api.get(reverse("concern-list"), HTTP_ORIGIN=impostor)
            assert not allowed(response), impostor

    def test_no_regexes_configured_by_default(self, settings):
        from django.conf import settings as live

        assert live.CORS_ALLOWED_ORIGIN_REGEXES == []
