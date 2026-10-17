import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.directory.models import (
    HealthConcern,
    Modality,
    Practitioner,
    RecommendationRequest,
)
from apps.outreach.models import ContactRequest

AUSTIN = {"latitude": 30.2672, "longitude": -97.7431}


@pytest.fixture
def directory(db):
    modality = Modality.objects.create(name="Acupuncture")
    concern = HealthConcern.objects.create(name="Chronic pain")
    concern.modalities.set([modality])
    practitioner = Practitioner.objects.create(
        display_name="Maya Ellison",
        email="maya@example.com",
        latitude=30.26,
        longitude=-97.74,
        is_published=True,
    )
    practitioner.concerns.set([concern])
    practitioner.modalities.set([modality])
    return {"concern": concern, "practitioner": practitioner}


def run_search(api, directory):
    return api.post(
        reverse("recommendation-create"),
        {"concerns": [str(directory["concern"].id)], **AUSTIN},
        format="json",
    ).json()


@pytest.mark.django_db
class TestSavedSearches:
    def test_requires_sign_in(self, api):
        assert api.get(reverse("patient-searches")).status_code == 401

    def test_lists_searches_made_while_signed_in(self, auth_api, directory, user):
        run_search(auth_api, directory)

        body = auth_api.get(reverse("patient-searches")).json()

        assert body["count"] == 1
        row = body["results"][0]
        assert row["location_label"] or row["result_count"] == 1
        assert row["practitioner_names"] == ["Maya Ellison"]
        assert [c["name"] for c in row["concerns"]] == ["Chronic pain"]

    def test_does_not_list_anonymous_searches(self, auth_api, directory):
        run_search(APIClient(), directory)  # anonymous, belongs to nobody

        assert auth_api.get(reverse("patient-searches")).json()["count"] == 0

    def test_one_patient_cannot_see_anothers(self, auth_api, directory, user):
        other = User.objects.create_user(
            email="other@example.com", password="pw-123456789"
        )
        their_client = APIClient()
        their_client.force_authenticate(user=other)
        run_search(their_client, directory)

        assert auth_api.get(reverse("patient-searches")).json()["count"] == 0

    def test_newest_first(self, auth_api, directory):
        run_search(auth_api, directory)
        second = run_search(auth_api, directory)

        body = auth_api.get(reverse("patient-searches")).json()

        assert body["results"][0]["id"] == second["id"]


@pytest.mark.django_db
class TestClaimingASearch:
    def test_an_anonymous_search_can_be_claimed_after_signing_up(
        self, auth_api, directory, user
    ):
        """The homepage works without an account, so nearly every patient's
        first searches are anonymous. Without claiming, their dashboard would
        be empty however much they had used the site."""
        anonymous = run_search(APIClient(), directory)

        response = auth_api.post(
            reverse("patient-claim-search"),
            {"id": anonymous["id"], "token": anonymous["claim_token"]},
            format="json",
        )

        assert response.status_code == 200
        assert RecommendationRequest.objects.get(id=anonymous["id"]).user == user
        assert auth_api.get(reverse("patient-searches")).json()["count"] == 1

    def test_a_wrong_token_is_not_found(self, auth_api, directory):
        anonymous = run_search(APIClient(), directory)

        response = auth_api.post(
            reverse("patient-claim-search"),
            {"id": anonymous["id"], "token": "wrong"},
            format="json",
        )

        assert response.status_code == 404

    def test_claiming_is_idempotent_for_the_same_account(self, auth_api, directory):
        anonymous = run_search(APIClient(), directory)
        payload = {"id": anonymous["id"], "token": anonymous["claim_token"]}

        auth_api.post(reverse("patient-claim-search"), payload, format="json")
        again = auth_api.post(reverse("patient-claim-search"), payload, format="json")

        assert again.status_code == 200
        assert RecommendationRequest.objects.count() == 1

    def test_a_search_cannot_be_taken_from_another_account(self, auth_api, directory):
        owner = User.objects.create_user(
            email="owner@example.com", password="pw-123456789"
        )
        their_client = APIClient()
        their_client.force_authenticate(user=owner)
        theirs = run_search(their_client, directory)

        response = auth_api.post(
            reverse("patient-claim-search"),
            {"id": theirs["id"], "token": theirs["claim_token"]},
            format="json",
        )

        assert response.status_code == 409
        assert RecommendationRequest.objects.get(id=theirs["id"]).user == owner

    def test_claiming_requires_sign_in(self, api, directory):
        anonymous = run_search(APIClient(), directory)

        response = api.post(
            reverse("patient-claim-search"),
            {"id": anonymous["id"], "token": anonymous["claim_token"]},
            format="json",
        )

        assert response.status_code == 401


@pytest.mark.django_db
class TestSavedEnquiries:
    def _send(self, client, directory, **extra):
        return client.post(
            reverse("contact-request-create"),
            {
                "practitioner": str(directory["practitioner"].id),
                "name": "Ada Lovelace",
                "email": "ada@example.com",
                "consent": True,
                **extra,
            },
            format="json",
        )

    def test_requires_sign_in(self, api):
        assert api.get(reverse("patient-enquiries")).status_code == 401

    def test_lists_enquiries_sent_while_signed_in(self, auth_api, directory):
        self._send(auth_api, directory)

        body = auth_api.get(reverse("patient-enquiries")).json()

        assert body["count"] == 1
        assert body["results"][0]["practitioner_name"] == "Maya Ellison"
        assert body["results"][0]["status"] == "new"

    def test_shows_the_patient_what_they_agreed_to(self, auth_api, directory):
        self._send(auth_api, directory)

        row = auth_api.get(reverse("patient-enquiries")).json()["results"][0]

        assert "share my name and contact details" in row["consent_text"]

    def test_the_practitioners_private_note_is_not_exposed(self, auth_api, directory):
        self._send(auth_api, directory)
        ContactRequest.objects.update(practitioner_note="Difficult caller")

        row = auth_api.get(reverse("patient-enquiries")).json()["results"][0]

        assert "practitioner_note" not in row

    def test_progress_is_visible_to_the_patient(self, auth_api, directory):
        self._send(auth_api, directory)
        contact = ContactRequest.objects.get()
        contact.mark_viewed()

        row = auth_api.get(reverse("patient-enquiries")).json()["results"][0]

        assert row["status"] == "viewed"
        assert row["first_viewed_at"] is not None

    def test_does_not_list_anonymous_enquiries(self, auth_api, directory):
        self._send(APIClient(), directory)  # anonymous

        assert auth_api.get(reverse("patient-enquiries")).json()["count"] == 0


@pytest.mark.django_db
class TestLinkingWithARealToken:
    """`force_authenticate` bypasses authentication classes entirely, so it
    cannot catch a view that has them switched off. These sign in for real."""

    def _bearer(self, api, email="ada@example.com", password="patient-pw-12345"):
        User.objects.create_user(email=email, password=password)
        token = api.post(
            reverse("login"), {"email": email, "password": password}, format="json"
        ).json()["access"]
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return client

    def test_a_search_made_with_a_token_reaches_the_dashboard(self, api, directory):
        client = self._bearer(api)

        run_search(client, directory)

        assert client.get(reverse("patient-searches")).json()["count"] == 1

    def test_an_enquiry_made_with_a_token_reaches_the_dashboard(self, api, directory):
        client = self._bearer(api)

        client.post(
            reverse("contact-request-create"),
            {
                "practitioner": str(directory["practitioner"].id),
                "name": "Ada Lovelace",
                "email": "ada@example.com",
                "consent": True,
            },
            format="json",
        )

        assert client.get(reverse("patient-enquiries")).json()["count"] == 1

    def test_anonymous_searching_still_works(self, api, directory):
        """Authentication being on must not require it."""
        response = api.post(
            reverse("recommendation-create"),
            {"concerns": [str(directory["concern"].id)], **AUSTIN},
            format="json",
        )

        assert response.status_code == 201
        assert RecommendationRequest.objects.get().user_id is None
