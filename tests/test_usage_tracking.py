from datetime import date

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.analytics.models import DailyStat, PractitionerEvent
from apps.directory.models import (
    HealthConcern,
    Modality,
    Practitioner,
    RecommendationRequest,
)

AUSTIN = {"latitude": 30.2672, "longitude": -97.7431}


@pytest.fixture
def directory(db):
    modality = Modality.objects.create(name="Acupuncture")
    concern = HealthConcern.objects.create(name="Chronic pain")
    concern.modalities.set([modality])
    practitioners = []
    for index, tier in enumerate(("partner", "standard")):
        practitioner = Practitioner.objects.create(
            display_name=f"Practitioner {index}",
            latitude=30.26,
            longitude=-97.74,
            tier=tier,
            is_published=True,
        )
        practitioner.concerns.set([concern])
        practitioner.modalities.set([modality])
        practitioners.append(practitioner)
    return {"concern": concern, "practitioners": practitioners}


def run_search(api, directory, **extra):
    return api.post(
        reverse("recommendation-create"),
        {"concerns": [str(directory["concern"].id)], **AUSTIN, **extra},
        format="json",
    )


@pytest.mark.django_db
class TestSearchTracking:
    def test_the_search_is_stored_with_its_result_count(self, api, directory):
        run_search(api, directory)

        stored = RecommendationRequest.objects.get()
        assert stored.result_count == 2
        assert stored.ip_hash
        assert stored.location_label or stored.latitude

    def test_a_zero_result_search_is_recorded_not_discarded(self, api, directory):
        Practitioner.objects.update(is_published=False)

        run_search(api, directory)

        stored = RecommendationRequest.objects.get()
        assert stored.result_count == 0

    def test_impressions_are_written_for_every_recommendation(self, api, directory):
        run_search(api, directory)

        impressions = PractitionerEvent.objects.filter(
            kind=PractitionerEvent.Kind.IMPRESSION
        )
        assert impressions.count() == 2
        assert set(impressions.values_list("tier_at_event", flat=True)) == {
            "partner",
            "standard",
        }

    def test_impressions_cannot_be_inflated_by_the_client(self, api, directory):
        """Impressions come from the server, so `impression` is not an accepted
        value on the public event endpoint."""
        practitioner = directory["practitioners"][0]

        response = api.post(
            reverse("practitioner-event"),
            {"practitioner": str(practitioner.id), "kind": "impression"},
            format="json",
        )

        assert response.status_code == 400


@pytest.mark.django_db
class TestClickTracking:
    def test_a_click_is_recorded(self, api, directory):
        practitioner = directory["practitioners"][0]

        response = api.post(
            reverse("practitioner-event"),
            {"practitioner": str(practitioner.id), "kind": "website"},
            format="json",
        )

        assert response.status_code == 204
        event = PractitionerEvent.objects.get(kind="website")
        assert event.practitioner == practitioner
        assert event.tier_at_event == "partner"

    def test_a_click_can_be_tied_to_the_search_that_produced_it(self, api, directory):
        created = run_search(api, directory).json()
        practitioner = directory["practitioners"][0]

        api.post(
            reverse("practitioner-event"),
            {
                "practitioner": str(practitioner.id),
                "kind": "phone",
                "request_id": created["id"],
            },
            format="json",
        )

        event = PractitionerEvent.objects.get(kind="phone")
        assert str(event.request_id) == created["id"]

    def test_unpublished_practitioners_are_rejected(self, api, directory):
        practitioner = directory["practitioners"][0]
        Practitioner.objects.filter(id=practitioner.id).update(is_published=False)

        response = api.post(
            reverse("practitioner-event"),
            {"practitioner": str(practitioner.id), "kind": "website"},
            format="json",
        )

        assert response.status_code == 400


@pytest.mark.django_db
class TestRollup:
    def test_rollup_summarises_the_day(self, api, directory):
        run_search(api, directory)
        run_search(api, directory)
        api.post(
            reverse("practitioner-event"),
            {"practitioner": str(directory["practitioners"][0].id), "kind": "website"},
            format="json",
        )

        call_command("rollup_usage", days=1)

        stat = DailyStat.objects.get(day=date.today())
        assert stat.searches == 2
        assert stat.recommendations_served == 4
        assert stat.practitioner_impressions == 4
        assert stat.practitioner_clicks == 1
        assert stat.unique_visitors == 1

    def test_rollup_counts_coverage_gaps(self, api, directory):
        Practitioner.objects.update(is_published=False)
        run_search(api, directory)

        call_command("rollup_usage", days=1)

        stat = DailyStat.objects.get(day=date.today())
        assert stat.zero_result_searches == 1

    def test_rollup_is_idempotent(self, api, directory):
        run_search(api, directory)

        call_command("rollup_usage", days=1)
        call_command("rollup_usage", days=1)

        assert DailyStat.objects.count() == 1
        assert DailyStat.objects.get().searches == 1

    def test_rollup_records_emails_captured(self, api, directory, settings):
        settings.ANON_SEARCH_LIMIT_PER_DAY = 0
        run_search(api, directory, email="patient@example.com")

        call_command("rollup_usage", days=1)

        assert DailyStat.objects.get(day=date.today()).emails_captured == 1

    def test_click_through_rate(self):
        stat = DailyStat(practitioner_impressions=10, practitioner_clicks=3)
        assert stat.click_through_rate == pytest.approx(0.3)

    def test_click_through_rate_with_no_impressions(self):
        assert DailyStat().click_through_rate == 0.0


@pytest.mark.django_db
class TestPrune:
    def test_prune_leaves_recent_rows(self, api, directory):
        run_search(api, directory)

        call_command("prune_usage", days=90)

        assert PractitionerEvent.objects.exists()
