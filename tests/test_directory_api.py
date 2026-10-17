import pytest
from django.urls import reverse

from apps.directory.models import (
    HealthConcern,
    Modality,
    Practitioner,
    RecommendationRequest,
)

AUSTIN = {"latitude": 30.2672, "longitude": -97.7431}


@pytest.fixture
def seeded(db):
    acupuncture = Modality.objects.create(name="Acupuncture")
    chiro = Modality.objects.create(name="Chiropractic")
    pain = HealthConcern.objects.create(name="Chronic pain")
    pain.modalities.set([acupuncture, chiro])

    practitioners = []
    for index, tier in enumerate(("partner", "verified", "standard", "standard")):
        practitioner = Practitioner.objects.create(
            display_name=f"Practitioner {index}",
            latitude=30.26 + index * 0.001,
            longitude=-97.74,
            tier=tier,
            is_published=True,
        )
        practitioner.modalities.set([acupuncture])
        practitioner.concerns.set([pain])
        practitioners.append(practitioner)

    return {
        "acupuncture": acupuncture,
        "chiro": chiro,
        "pain": pain,
        "practitioners": practitioners,
    }


@pytest.mark.django_db
class TestPublicOptions:
    def test_modalities_are_public(self, api, seeded):
        response = api.get(reverse("modality-list"))

        assert response.status_code == 200
        assert {m["name"] for m in response.json()} == {"Acupuncture", "Chiropractic"}

    def test_concerns_are_public_and_carry_related_modalities(self, api, seeded):
        response = api.get(reverse("concern-list"))

        assert response.status_code == 200
        body = response.json()
        assert body[0]["name"] == "Chronic pain"
        assert set(body[0]["modalities"]) == {"acupuncture", "chiropractic"}

    def test_inactive_options_are_hidden(self, api, seeded):
        Modality.objects.filter(name="Chiropractic").update(is_active=False)

        names = {m["name"] for m in api.get(reverse("modality-list")).json()}

        assert names == {"Acupuncture"}


@pytest.mark.django_db
class TestRecommendationCreate:
    def test_anonymous_visitor_gets_at_most_three_recommendations(self, api, seeded):
        response = api.post(
            reverse("recommendation-create"),
            {"concerns": [str(seeded["pain"].id)], **AUSTIN},
            format="json",
        )

        assert response.status_code == 201
        body = response.json()
        assert len(body["recommendations"]) == 3
        assert [r["rank"] for r in body["recommendations"]] == [1, 2, 3]
        assert body["claim_token"]

    def test_results_are_ranked_with_preferred_tiers_first(self, api, seeded):
        response = api.post(
            reverse("recommendation-create"),
            {"concerns": [str(seeded["pain"].id)], **AUSTIN},
            format="json",
        )

        recommendations = response.json()["recommendations"]
        tiers = [r["practitioner"]["tier"] for r in recommendations]
        assert tiers[0] == "partner"
        assert tiers[1] == "verified"
        assert recommendations[0]["practitioner"]["is_preferred"] is True

    def test_each_recommendation_explains_itself(self, api, seeded):
        response = api.post(
            reverse("recommendation-create"),
            {"concerns": [str(seeded["pain"].id)], **AUSTIN},
            format="json",
        )

        for recommendation in response.json()["recommendations"]:
            assert recommendation["reasons"], "every card must carry its reasoning"
            assert recommendation["distance_miles"] is not None

    def test_free_text_location_is_geocoded(self, api, seeded):
        response = api.post(
            reverse("recommendation-create"),
            {"concerns": [str(seeded["pain"].id)], "location_label": "Austin"},
            format="json",
        )

        assert response.status_code == 201
        assert response.json()["location_label"] == "Austin, TX, USA"
        assert len(response.json()["recommendations"]) == 3

    def test_unknown_location_is_rejected_with_a_useful_message(self, api, seeded):
        response = api.post(
            reverse("recommendation-create"),
            {"concerns": [str(seeded["pain"].id)], "location_label": "Nowheresville"},
            format="json",
        )

        assert response.status_code == 400
        assert "location_label" in response.json()["errors"]

    def test_requires_at_least_one_concern_or_modality(self, api, seeded):
        response = api.post(reverse("recommendation-create"), AUSTIN, format="json")

        assert response.status_code == 400

    def test_requires_a_location(self, api, seeded):
        response = api.post(
            reverse("recommendation-create"),
            {"concerns": [str(seeded["pain"].id)]},
            format="json",
        )

        assert response.status_code == 400
        assert "location_label" in response.json()["errors"]

    def test_run_is_linked_to_a_signed_in_patient(self, auth_api, seeded, user):
        auth_api.post(
            reverse("recommendation-create"),
            {"concerns": [str(seeded["pain"].id)], **AUSTIN},
            format="json",
        )

        assert RecommendationRequest.objects.filter(user=user).count() == 1

    def test_no_matches_returns_an_empty_list_not_an_error(self, api, seeded):
        Practitioner.objects.update(is_published=False)

        response = api.post(
            reverse("recommendation-create"),
            {"concerns": [str(seeded["pain"].id)], **AUSTIN},
            format="json",
        )

        assert response.status_code == 201
        assert response.json()["recommendations"] == []


@pytest.mark.django_db
class TestRecommendationRetrieval:
    def _create(self, api, seeded):
        return api.post(
            reverse("recommendation-create"),
            {"concerns": [str(seeded["pain"].id)], **AUSTIN},
            format="json",
        ).json()

    def test_can_be_reopened_with_its_claim_token(self, api, seeded):
        created = self._create(api, seeded)

        response = api.get(
            reverse("recommendation-detail", args=[created["id"]]),
            {"token": created["claim_token"]},
        )

        assert response.status_code == 200
        assert len(response.json()["recommendations"]) == 3

    def test_wrong_token_is_not_found(self, api, seeded):
        created = self._create(api, seeded)

        response = api.get(
            reverse("recommendation-detail", args=[created["id"]]), {"token": "wrong"}
        )

        assert response.status_code == 404

    def test_missing_token_is_not_found(self, api, seeded):
        created = self._create(api, seeded)

        response = api.get(reverse("recommendation-detail", args=[created["id"]]))

        assert response.status_code == 404


@pytest.mark.django_db
class TestPractitionerDetail:
    def test_published_practitioner_is_public(self, api, seeded):
        practitioner = seeded["practitioners"][0]

        response = api.get(reverse("practitioner-detail", args=[practitioner.id]))

        assert response.status_code == 200
        assert response.json()["display_name"] == practitioner.display_name

    def test_unpublished_practitioner_is_hidden(self, api, seeded):
        practitioner = seeded["practitioners"][0]
        Practitioner.objects.filter(id=practitioner.id).update(is_published=False)

        assert (
            api.get(reverse("practitioner-detail", args=[practitioner.id])).status_code
            == 404
        )


@pytest.mark.django_db
class TestMapConfig:
    def test_reports_maps_disabled_without_a_key(self, api, settings):
        settings.GOOGLE_MAPS_BROWSER_KEY = ""

        response = api.get(reverse("map-config"))

        assert response.json() == {"google_maps_api_key": "", "maps_enabled": False}

    def test_serves_the_browser_key_when_configured(self, api, settings):
        settings.GOOGLE_MAPS_BROWSER_KEY = "browser-key-123"

        response = api.get(reverse("map-config"))

        assert response.json() == {
            "google_maps_api_key": "browser-key-123",
            "maps_enabled": True,
        }
