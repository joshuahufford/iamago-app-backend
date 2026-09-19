import pytest
from django.core import mail
from django.urls import reverse

from apps.accounts.models import User
from apps.directory.models import HealthConcern, Modality, Practitioner
from apps.outreach.models import ContactRequest, ContactRequestAccess
from apps.outreach.serializers import CONSENT_TEXT, CONSENT_TEXT_WITH_CONCERNS

AUSTIN = {"latitude": 30.2672, "longitude": -97.7431}


@pytest.fixture
def practitioner(db):
    modality = Modality.objects.create(name="Acupuncture")
    concern = HealthConcern.objects.create(name="Chronic pain")
    concern.modalities.set([modality])
    practitioner = Practitioner.objects.create(
        display_name="Maya Ellison",
        email="maya@example.com",
        latitude=30.26,
        longitude=-97.74,
        tier="partner",
        is_published=True,
    )
    practitioner.concerns.set([concern])
    practitioner.modalities.set([modality])
    return practitioner


@pytest.fixture
def search(api, practitioner, db):
    concern = practitioner.concerns.first()
    return api.post(
        reverse("recommendation-create"),
        {"concerns": [str(concern.id)], **AUSTIN},
        format="json",
    ).json()


def ask(api, practitioner, **extra):
    payload = {
        "practitioner": str(practitioner.id),
        "name": "Ada Lovelace",
        "email": "ada@example.com",
        "phone": "+1 512 555 0111",
        "message": "My back has hurt for months.",
        "consent": True,
        **extra,
    }
    return api.post(reverse("contact-request-create"), payload, format="json")


@pytest.mark.django_db
class TestContactRequest:
    def test_a_patient_can_ask_to_be_contacted(self, api, practitioner):
        response = ask(api, practitioner)

        assert response.status_code == 201
        contact = ContactRequest.objects.get()
        assert contact.name == "Ada Lovelace"
        assert contact.practitioner == practitioner
        assert contact.status == ContactRequest.Status.NEW

    def test_the_response_does_not_leak_the_patient_record_back(self, api, practitioner):
        body = ask(api, practitioner).json()

        assert set(body) == {"id", "practitioner_name", "created_at"}
        assert body["practitioner_name"] == "Maya Ellison"

    def test_consent_is_required(self, api, practitioner):
        response = ask(api, practitioner, consent=False)

        assert response.status_code == 400
        assert "consent" in response.json()["errors"]
        assert not ContactRequest.objects.exists()

    def test_the_agreed_wording_is_stored_verbatim(self, api, practitioner):
        ask(api, practitioner)

        assert ContactRequest.objects.get().consent_text == CONSENT_TEXT

    def test_sharing_concerns_records_the_wider_wording(self, api, practitioner):
        ask(api, practitioner, share_concerns=True)

        assert ContactRequest.objects.get().consent_text == CONSENT_TEXT_WITH_CONCERNS

    def test_concerns_are_withheld_unless_the_patient_shared_them(
        self, api, practitioner, search
    ):
        ask(
            api,
            practitioner,
            recommendation_request=search["id"],
            share_concerns=False,
        )

        assert ContactRequest.objects.get().shared_concerns == []

    def test_shared_concerns_are_available_when_consent_was_given(
        self, api, practitioner, search
    ):
        ask(
            api,
            practitioner,
            recommendation_request=search["id"],
            share_concerns=True,
        )

        shared = ContactRequest.objects.get().shared_concerns
        assert [c.name for c in shared] == ["Chronic pain"]

    def test_unpublished_practitioners_cannot_be_contacted(self, api, practitioner):
        Practitioner.objects.filter(id=practitioner.id).update(is_published=False)

        assert ask(api, practitioner).status_code == 400

    def test_the_raw_address_is_not_stored(self, api, practitioner):
        ask(api, practitioner)

        contact = ContactRequest.objects.get()
        assert contact.ip_hash and "127.0.0.1" not in contact.ip_hash

    def test_enquiries_have_their_own_daily_cap(self, api, practitioner, settings):
        settings.CONTACT_REQUEST_LIMIT_PER_DAY = 2

        assert ask(api, practitioner).status_code == 201
        assert ask(api, practitioner).status_code == 201
        assert ask(api, practitioner).status_code == 429

    def test_heavy_searching_does_not_block_enquiries(self, api, practitioner, settings):
        """Enquiring is the valuable action; it must not be spent by searching."""
        settings.ANON_SEARCH_LIMIT_PER_DAY = 1
        settings.CONTACT_REQUEST_LIMIT_PER_DAY = 5
        concern = practitioner.concerns.first()
        for _ in range(3):
            api.post(
                reverse("recommendation-create"),
                {"concerns": [str(concern.id)], **AUSTIN},
                format="json",
            )

        assert ask(api, practitioner).status_code == 201

    def test_supplying_an_email_does_not_raise_the_enquiry_ceiling(
        self, api, practitioner, settings
    ):
        """On this form the email is the patient's contact detail, not a
        credential — treating it as one would let the form bypass the limit."""
        settings.CONTACT_REQUEST_LIMIT_PER_DAY = 1
        settings.EMAIL_SEARCH_LIMIT_PER_DAY = 50

        assert ask(api, practitioner).status_code == 201
        assert ask(api, practitioner).status_code == 429


@pytest.mark.django_db
class TestContactNotifications:
    def test_both_sides_are_emailed(self, api, practitioner):
        ask(api, practitioner)

        assert len(mail.outbox) == 2
        recipients = {message.to[0] for message in mail.outbox}
        assert recipients == {"maya@example.com", "ada@example.com"}

    def test_the_practitioner_can_reply_straight_to_the_patient(self, api, practitioner):
        ask(api, practitioner)

        to_practitioner = next(m for m in mail.outbox if m.to == ["maya@example.com"])
        assert to_practitioner.reply_to == ["ada@example.com"]
        assert "Ada Lovelace" in to_practitioner.body

    def test_concerns_are_not_emailed_without_consent(self, api, practitioner, search):
        ask(api, practitioner, recommendation_request=search["id"], share_concerns=False)

        to_practitioner = next(m for m in mail.outbox if m.to == ["maya@example.com"])
        assert "Chronic pain" not in to_practitioner.body

    def test_concerns_are_emailed_when_shared(self, api, practitioner, search):
        ask(api, practitioner, recommendation_request=search["id"], share_concerns=True)

        to_practitioner = next(m for m in mail.outbox if m.to == ["maya@example.com"])
        assert "Chronic pain" in to_practitioner.body

    def test_the_request_survives_a_mail_failure(self, api, practitioner, settings):
        """Losing the enquiry would be far worse than losing its notification."""
        settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

        from unittest.mock import patch

        with patch(
            "apps.common.mail.EmailMultiAlternatives.send",
            side_effect=OSError("smtp down"),
        ):
            response = ask(api, practitioner)

        assert response.status_code == 201
        assert ContactRequest.objects.count() == 1


@pytest.mark.django_db
class TestEmailMyMatches:
    def test_sends_the_matches_to_the_given_address(self, api, practitioner, search):
        response = api.post(
            reverse("recommendations-email", args=[search["id"]]),
            {"token": search["claim_token"], "email": "ada@example.com"},
            format="json",
        )

        assert response.status_code == 204
        assert len(mail.outbox) == 1
        assert "Maya Ellison" in mail.outbox[0].body

    def test_a_wrong_token_is_not_found(self, api, practitioner, search):
        response = api.post(
            reverse("recommendations-email", args=[search["id"]]),
            {"token": "wrong", "email": "someone@example.com"},
            format="json",
        )

        assert response.status_code == 404
        assert mail.outbox == []

    def test_an_address_is_required(self, api, practitioner, search):
        response = api.post(
            reverse("recommendations-email", args=[search["id"]]),
            {"token": search["claim_token"]},
            format="json",
        )

        assert response.status_code == 400


@pytest.mark.django_db
class TestAuditTrail:
    def test_opening_an_enquiry_is_recorded(self, api, practitioner):
        ask(api, practitioner)
        contact = ContactRequest.objects.get()
        user = User.objects.create_user(email="maya@example.com", password="pw-123456789")
        practitioner.user = user
        practitioner.save()

        contact.mark_viewed(by=user, ip_hash="hash-abc")

        access = ContactRequestAccess.objects.get()
        assert access.actor == user
        assert access.contact_request == contact

    def test_the_first_view_is_timestamped_once(self, api, practitioner):
        ask(api, practitioner)
        contact = ContactRequest.objects.get()

        contact.mark_viewed()
        first = contact.first_viewed_at
        contact.mark_viewed()

        contact.refresh_from_db()
        assert contact.first_viewed_at == first
        # But every open is still logged.
        assert ContactRequestAccess.objects.count() == 2

    def test_viewing_moves_a_new_request_to_viewed(self, api, practitioner):
        ask(api, practitioner)
        contact = ContactRequest.objects.get()

        contact.mark_viewed()

        contact.refresh_from_db()
        assert contact.status == ContactRequest.Status.VIEWED
