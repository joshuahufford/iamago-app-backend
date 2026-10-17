import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.analytics.models import PractitionerEvent
from apps.directory.models import HealthConcern, Modality, Practitioner
from apps.outreach.models import ContactRequest, ContactRequestAccess

PASSWORD = "portal-pw-123456"


@pytest.fixture
def catalogue(db):
    modality = Modality.objects.create(name="Acupuncture")
    other = Modality.objects.create(name="Chiropractic")
    concern = HealthConcern.objects.create(name="Chronic pain")
    concern.modalities.set([modality])
    return {"modality": modality, "other": other, "concern": concern}


def make_practitioner(name, email, catalogue, *, tier="partner"):
    user = User.objects.create_user(email=email, password=PASSWORD)
    practitioner = Practitioner.objects.create(
        display_name=name,
        email=email,
        user=user,
        latitude=30.26,
        longitude=-97.74,
        tier=tier,
        is_published=True,
    )
    practitioner.modalities.set([catalogue["modality"]])
    practitioner.concerns.set([catalogue["concern"]])
    return practitioner


@pytest.fixture
def mine(catalogue):
    return make_practitioner("Maya Ellison", "maya@example.com", catalogue)


@pytest.fixture
def theirs(catalogue):
    return make_practitioner("Rival Clinic", "rival@example.com", catalogue)


@pytest.fixture
def portal(api, mine):
    api.force_authenticate(user=mine.user)
    return api


def enquiry(practitioner, name="Ada Lovelace", **extra):
    return ContactRequest.objects.create(
        practitioner=practitioner,
        name=name,
        email=f"{name.split()[0].lower()}@example.com",
        consent_text="agreed wording",
        **extra,
    )


@pytest.mark.django_db
class TestPortalAccess:
    def test_anonymous_visitors_are_refused(self, api, mine):
        assert api.get(reverse("portal-me")).status_code == 401

    def test_a_user_with_no_listing_is_refused(self, api, mine):
        stranger = User.objects.create_user(email="nobody@example.com", password=PASSWORD)
        api.force_authenticate(user=stranger)

        response = api.get(reverse("portal-me"))

        assert response.status_code == 403

    def test_a_claimed_practitioner_sees_their_listing(self, portal, mine):
        response = portal.get(reverse("portal-me"))

        assert response.status_code == 200
        assert response.json()["display_name"] == "Maya Ellison"


@pytest.mark.django_db
class TestPortalListingEditing:
    def test_a_practitioner_can_update_their_own_details(self, portal, mine, catalogue):
        response = portal.patch(
            reverse("portal-me"),
            {
                "practice_name": "Still Point Acupuncture",
                "accepting_new_patients": False,
                "modalities": [str(catalogue["other"].id)],
                "concerns": [str(catalogue["concern"].id)],
            },
            format="json",
        )

        assert response.status_code == 200
        mine.refresh_from_db()
        assert mine.practice_name == "Still Point Acupuncture"
        assert mine.accepting_new_patients is False
        assert [m.name for m in mine.modalities.all()] == ["Chiropractic"]

    def test_a_practitioner_cannot_promote_themselves_to_partner(self, portal, mine):
        Practitioner.objects.filter(id=mine.id).update(tier="standard")

        portal.patch(reverse("portal-me"), {"tier": "partner"}, format="json")

        mine.refresh_from_db()
        assert mine.tier == "standard"

    def test_a_practitioner_cannot_publish_their_own_listing(self, portal, mine):
        Practitioner.objects.filter(id=mine.id).update(is_published=False)

        portal.patch(reverse("portal-me"), {"is_published": True}, format="json")

        mine.refresh_from_db()
        assert mine.is_published is False

    def test_coordinates_are_not_editable_here(self, portal, mine):
        """A wrong pair silently breaks matching, so re-geocoding is an admin job."""
        portal.patch(reverse("portal-me"), {"latitude": 0, "longitude": 0}, format="json")

        mine.refresh_from_db()
        assert float(mine.latitude) == pytest.approx(30.26)


@pytest.mark.django_db
class TestPortalStats:
    def test_reports_impressions_clicks_and_enquiries(self, portal, mine):
        for _ in range(10):
            PractitionerEvent.objects.create(
                practitioner=mine, kind="impression", tier_at_event="partner"
            )
        for _ in range(2):
            PractitionerEvent.objects.create(
                practitioner=mine, kind="website", tier_at_event="partner"
            )
        PractitionerEvent.objects.create(
            practitioner=mine, kind="phone", tier_at_event="partner"
        )
        enquiry(mine)

        body = portal.get(reverse("portal-stats")).json()

        assert body["impressions"] == 10
        assert body["website_clicks"] == 2
        assert body["phone_reveals"] == 1
        assert body["clicks"] == 3
        assert body["click_through_rate"] == pytest.approx(0.3)
        assert body["contact_requests"] == 1
        assert body["new_contact_requests"] == 1

    def test_another_practitioners_numbers_are_not_included(self, portal, mine, theirs):
        PractitionerEvent.objects.create(
            practitioner=theirs, kind="impression", tier_at_event="partner"
        )
        enquiry(theirs, name="Someone Else")

        body = portal.get(reverse("portal-stats")).json()

        assert body["impressions"] == 0
        assert body["contact_requests"] == 0

    def test_the_window_is_configurable_and_bounded(self, portal, mine):
        assert portal.get(reverse("portal-stats"), {"days": 7}).json()["days"] == 7
        assert portal.get(reverse("portal-stats"), {"days": 9999}).json()["days"] == 365
        assert (
            portal.get(reverse("portal-stats"), {"days": "nonsense"}).json()["days"] == 30
        )

    def test_click_rate_with_no_impressions_does_not_divide_by_zero(self, portal, mine):
        assert portal.get(reverse("portal-stats")).json()["click_through_rate"] == 0.0


@pytest.mark.django_db
class TestPortalEnquiries:
    def test_lists_only_this_practitioners_enquiries(self, portal, mine, theirs):
        enquiry(mine, name="Ada Lovelace")
        enquiry(theirs, name="Not Yours")

        body = portal.get(reverse("portal-contact-requests")).json()

        names = [row["name"] for row in body["results"]]
        assert names == ["Ada Lovelace"]

    def test_another_practitioners_enquiry_is_not_found(self, portal, theirs):
        other = enquiry(theirs, name="Not Yours")

        response = portal.get(reverse("portal-contact-request-detail", args=[other.id]))

        assert response.status_code == 404

    def test_opening_an_enquiry_records_an_access(self, portal, mine):
        contact = enquiry(mine)

        portal.get(reverse("portal-contact-request-detail", args=[contact.id]))

        access = ContactRequestAccess.objects.get()
        assert access.contact_request == contact
        assert access.actor == mine.user

    def test_opening_marks_it_viewed(self, portal, mine):
        contact = enquiry(mine)

        portal.get(reverse("portal-contact-request-detail", args=[contact.id]))

        contact.refresh_from_db()
        assert contact.status == ContactRequest.Status.VIEWED
        assert contact.first_viewed_at is not None

    def test_concerns_are_withheld_from_the_portal_without_consent(
        self, portal, mine, api
    ):
        contact = enquiry(mine, share_concerns=False)

        body = portal.get(
            reverse("portal-contact-request-detail", args=[contact.id])
        ).json()

        assert body["concerns"] == []

    def test_a_practitioner_can_record_a_response(self, portal, mine):
        contact = enquiry(mine)

        response = portal.patch(
            reverse("portal-contact-request-detail", args=[contact.id]),
            {"status": "responded", "practitioner_note": "Called, booked for Tuesday."},
            format="json",
        )

        assert response.status_code == 200
        contact.refresh_from_db()
        assert contact.status == ContactRequest.Status.RESPONDED
        assert contact.responded_at is not None
        assert contact.practitioner_note == "Called, booked for Tuesday."

    def test_an_enquiry_cannot_be_moved_back_to_new(self, portal, mine):
        contact = enquiry(mine, status=ContactRequest.Status.RESPONDED)

        response = portal.patch(
            reverse("portal-contact-request-detail", args=[contact.id]),
            {"status": "new"},
            format="json",
        )

        assert response.status_code == 400

    def test_enquiries_can_be_filtered_by_status(self, portal, mine):
        enquiry(mine, name="New One")
        enquiry(mine, name="Done One", status=ContactRequest.Status.CLOSED)

        body = portal.get(reverse("portal-contact-requests"), {"status": "closed"}).json()

        assert [row["name"] for row in body["results"]] == ["Done One"]

    def test_the_patient_record_is_not_editable_from_the_portal(self, portal, mine):
        contact = enquiry(mine)

        portal.patch(
            reverse("portal-contact-request-detail", args=[contact.id]),
            {"name": "Rewritten", "email": "rewritten@example.com"},
            format="json",
        )

        contact.refresh_from_db()
        assert contact.name == "Ada Lovelace"
        assert contact.email == "ada@example.com"
