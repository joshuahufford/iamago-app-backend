import pytest
from django.urls import reverse

from apps.analytics.models import SearchQuota
from apps.analytics.services import client_ip, hash_ip, visitor_hash
from apps.directory.models import HealthConcern, Modality, Practitioner

AUSTIN = {"latitude": 30.2672, "longitude": -97.7431}


@pytest.fixture
def searchable(db):
    modality = Modality.objects.create(name="Acupuncture")
    concern = HealthConcern.objects.create(name="Chronic pain")
    concern.modalities.set([modality])
    practitioner = Practitioner.objects.create(
        display_name="Maya Ellison",
        latitude=30.26,
        longitude=-97.74,
        is_published=True,
    )
    practitioner.concerns.set([concern])
    practitioner.modalities.set([modality])
    return concern


def search(api, concern, **extra):
    return api.post(
        reverse("recommendation-create"),
        {"concerns": [str(concern.id)], **AUSTIN, **extra},
        format="json",
    )


@pytest.mark.django_db
class TestSearchLimit:
    def test_free_searches_are_allowed(self, api, searchable, settings):
        settings.ANON_SEARCH_LIMIT_PER_DAY = 3

        for _ in range(3):
            assert search(api, searchable).status_code == 201

    def test_asks_for_an_email_once_the_free_allowance_is_spent(
        self, api, searchable, settings
    ):
        settings.ANON_SEARCH_LIMIT_PER_DAY = 2

        for _ in range(2):
            search(api, searchable)
        response = search(api, searchable)

        assert response.status_code == 429
        assert response.json()["code"] == "email_required"

    def test_an_email_raises_the_ceiling(self, api, searchable, settings):
        settings.ANON_SEARCH_LIMIT_PER_DAY = 2
        settings.EMAIL_SEARCH_LIMIT_PER_DAY = 5

        for _ in range(2):
            search(api, searchable)
        assert search(api, searchable).status_code == 429

        response = search(api, searchable, email="patient@example.com")

        assert response.status_code == 201

    def test_an_email_does_not_remove_the_ceiling(self, api, searchable, settings):
        """An email is a speed bump for a scraper, not a licence."""
        settings.ANON_SEARCH_LIMIT_PER_DAY = 1
        settings.EMAIL_SEARCH_LIMIT_PER_DAY = 3

        for _ in range(3):
            search(api, searchable, email="scraper@example.com")
        response = search(api, searchable, email="scraper@example.com")

        assert response.status_code == 429
        assert response.json()["code"] == "rate_limited"

    def test_the_email_is_stored_on_the_search(self, api, searchable, settings):
        settings.ANON_SEARCH_LIMIT_PER_DAY = 0

        response = search(api, searchable, email="patient@example.com")

        assert response.status_code == 201
        assert response.json()["id"]

    def test_refusals_are_counted(self, api, searchable, settings):
        settings.ANON_SEARCH_LIMIT_PER_DAY = 1

        search(api, searchable)
        search(api, searchable)

        quota = SearchQuota.objects.get()
        assert quota.search_count == 1
        assert quota.blocked_count == 1

    def test_remaining_allowance_is_reported(self, api, searchable, settings):
        settings.ANON_SEARCH_LIMIT_PER_DAY = 5

        response = search(api, searchable)

        assert response["X-Search-Remaining"] == "4"

    def test_a_blocked_search_creates_no_recommendation_request(
        self, api, searchable, settings
    ):
        from apps.directory.models import RecommendationRequest

        settings.ANON_SEARCH_LIMIT_PER_DAY = 1
        search(api, searchable)
        search(api, searchable)

        assert RecommendationRequest.objects.count() == 1


@pytest.mark.django_db
class TestVisitorHashing:
    def test_the_raw_address_is_never_the_stored_value(self, api, searchable, settings):
        settings.ANON_SEARCH_LIMIT_PER_DAY = 5
        search(api, searchable)

        quota = SearchQuota.objects.get()
        assert quota.ip_hash
        assert "127.0.0.1" not in quota.ip_hash
        assert len(quota.ip_hash) == 64

    def test_hashing_is_stable_and_salted(self, settings):
        settings.IP_HASH_SALT = "salt-one"
        first = hash_ip("203.0.113.5")
        assert first == hash_ip("203.0.113.5")

        settings.IP_HASH_SALT = "salt-two"
        assert hash_ip("203.0.113.5") != first

    def test_forwarded_header_is_ignored_without_a_configured_proxy(self, rf, settings):
        """X-Forwarded-For is client-supplied. Trusting it blindly would let
        anyone forge an address and reset their own limit."""
        settings.TRUSTED_PROXY_COUNT = 0
        request = rf.get("/", HTTP_X_FORWARDED_FOR="1.2.3.4", REMOTE_ADDR="10.0.0.1")

        assert client_ip(request) == "10.0.0.1"

    def test_forwarded_header_is_used_when_a_proxy_is_configured(self, rf, settings):
        settings.TRUSTED_PROXY_COUNT = 1
        request = rf.get(
            "/", HTTP_X_FORWARDED_FOR="9.9.9.9, 1.2.3.4", REMOTE_ADDR="10.0.0.1"
        )

        assert client_ip(request) == "1.2.3.4"

    def test_different_visitors_get_separate_allowances(self, rf, settings):
        settings.TRUSTED_PROXY_COUNT = 0
        one = rf.get("/", REMOTE_ADDR="10.0.0.1")
        two = rf.get("/", REMOTE_ADDR="10.0.0.2")

        assert visitor_hash(one) != visitor_hash(two)
