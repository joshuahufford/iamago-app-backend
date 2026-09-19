"""The admin is the product for whoever curates the directory, so it gets the
same treatment as the public API: every screen loads, every action does what it
says, and nothing 500s on an empty database.
"""

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.analytics.models import DailyStat, PractitionerEvent, SearchQuota
from apps.directory.models import HealthConcern, Modality, Practitioner

ADMIN_MODELS = [
    ("accounts", "user"),
    ("directory", "modality"),
    ("directory", "healthconcern"),
    ("directory", "practitioner"),
    ("directory", "recommendationrequest"),
    ("analytics", "dailystat"),
    ("analytics", "practitionerevent"),
    ("analytics", "searchquota"),
]


@pytest.fixture
def staff_client(client, db):
    User.objects.create_superuser(email="admin@example.com", password="admin-pw-12345")
    client.login(email="admin@example.com", password="admin-pw-12345")
    return client


@pytest.fixture
def catalogue(db):
    modality = Modality.objects.create(name="Acupuncture")
    concern = HealthConcern.objects.create(name="Chronic pain")
    concern.modalities.set([modality])
    return {"modality": modality, "concern": concern}


@pytest.mark.django_db
class TestAdminPagesLoad:
    @pytest.mark.parametrize("app_label,model_name", ADMIN_MODELS)
    def test_changelist_loads_on_an_empty_database(
        self, staff_client, app_label, model_name
    ):
        url = reverse(f"admin:{app_label}_{model_name}_changelist")

        assert staff_client.get(url).status_code == 200

    @pytest.mark.parametrize(
        "app_label,model_name",
        [
            ("directory", "modality"),
            ("directory", "healthconcern"),
            ("directory", "practitioner"),
        ],
    )
    def test_add_form_loads(self, staff_client, app_label, model_name):
        url = reverse(f"admin:{app_label}_{model_name}_add")

        assert staff_client.get(url).status_code == 200

    def test_index_loads(self, staff_client):
        assert staff_client.get(reverse("admin:index")).status_code == 200

    def test_practitioner_changelist_loads_with_data(self, staff_client, catalogue):
        practitioner = Practitioner.objects.create(display_name="Maya Ellison")
        practitioner.concerns.set([catalogue["concern"]])
        PractitionerEvent.objects.create(
            practitioner=practitioner, kind="impression", tier_at_event="standard"
        )

        response = staff_client.get(reverse("admin:directory_practitioner_changelist"))

        assert response.status_code == 200
        assert b"Maya Ellison" in response.content


@pytest.mark.django_db
class TestPractitionerCreation:
    def test_a_practitioner_can_be_added_through_the_form(self, staff_client, catalogue):
        response = staff_client.post(
            reverse("admin:directory_practitioner_add"),
            {
                "display_name": "Grace Okonkwo",
                "credentials": "ND",
                "practice_name": "Willow Clinic",
                "bio": "",
                "photo_url": "",
                "years_experience": "",
                "tier": "verified",
                "is_published": "on",
                "modalities": [str(catalogue["modality"].id)],
                "concerns": [str(catalogue["concern"].id)],
                "accepting_new_patients": "on",
                "address_line1": "",
                "address_line2": "",
                "city": "Denver",
                "region": "CO",
                "postal_code": "80206",
                "country": "US",
                "latitude": "39.73",
                "longitude": "-104.95",
                "website": "",
                "phone": "",
                "email": "",
            },
        )

        assert response.status_code == 302
        created = Practitioner.objects.get(display_name="Grace Okonkwo")
        assert created.tier == "verified"
        assert created.is_published is True
        assert list(created.concerns.all()) == [catalogue["concern"]]

    def test_a_modality_can_be_added_through_the_form(self, staff_client):
        response = staff_client.post(
            reverse("admin:directory_modality_add"),
            {
                "name": "Reiki",
                "slug": "reiki",
                "description": "",
                "sort_order": "0",
                "is_active": "on",
            },
        )

        assert response.status_code == 302
        assert Modality.objects.filter(name="Reiki").exists()


@pytest.mark.django_db
class TestPractitionerActions:
    def _run(self, staff_client, action, practitioners):
        return staff_client.post(
            reverse("admin:directory_practitioner_changelist"),
            {
                "action": action,
                "_selected_action": [str(p.id) for p in practitioners],
            },
            follow=True,
        )

    def test_publish_action(self, staff_client, catalogue):
        practitioner = Practitioner.objects.create(
            display_name="Draft", latitude=30.2, longitude=-97.7
        )

        self._run(staff_client, "action_publish", [practitioner])

        practitioner.refresh_from_db()
        assert practitioner.is_published is True

    def test_publish_warns_about_listings_with_no_coordinates(self, staff_client):
        practitioner = Practitioner.objects.create(display_name="Nowhere")

        response = self._run(staff_client, "action_publish", [practitioner])

        assert b"no coordinates" in response.content

    def test_unpublish_action(self, staff_client):
        practitioner = Practitioner.objects.create(display_name="Live", is_published=True)

        self._run(staff_client, "action_unpublish", [practitioner])

        practitioner.refresh_from_db()
        assert practitioner.is_published is False

    def test_tier_actions(self, staff_client):
        practitioner = Practitioner.objects.create(display_name="Someone")

        self._run(staff_client, "action_mark_partner", [practitioner])
        practitioner.refresh_from_db()
        assert practitioner.tier == "partner"

        self._run(staff_client, "action_mark_standard", [practitioner])
        practitioner.refresh_from_db()
        assert practitioner.tier == "standard"

    def test_geocode_action_fills_in_coordinates(self, staff_client, settings):
        settings.GOOGLE_MAPS_API_KEY = ""
        practitioner = Practitioner.objects.create(
            display_name="Denver ND", city="Denver"
        )

        self._run(staff_client, "action_geocode", [practitioner])

        practitioner.refresh_from_db()
        assert practitioner.latitude is not None
        assert float(practitioner.latitude) == pytest.approx(39.7392, abs=0.01)

    def test_geocode_action_reports_what_it_could_not_find(self, staff_client, settings):
        settings.GOOGLE_MAPS_API_KEY = ""
        practitioner = Practitioner.objects.create(display_name="Mystery", city="Zzzz")

        response = self._run(staff_client, "action_geocode", [practitioner])

        assert b"Could not locate" in response.content

    def test_csv_export(self, staff_client, catalogue):
        practitioner = Practitioner.objects.create(
            display_name="Maya Ellison", city="Austin"
        )
        practitioner.modalities.set([catalogue["modality"]])

        response = self._run(staff_client, "action_export_csv", [practitioner])

        assert response["Content-Type"] == "text/csv"
        body = response.content.decode()
        assert "display_name" in body
        assert "Maya Ellison" in body
        assert "Acupuncture" in body


@pytest.mark.django_db
class TestCsvImport:
    def _upload(self, staff_client, text, **extra):
        from django.core.files.uploadedfile import SimpleUploadedFile

        return staff_client.post(
            reverse("admin:directory_practitioner_import_csv"),
            {
                "csv_file": SimpleUploadedFile("p.csv", text.encode(), "text/csv"),
                **extra,
            },
            follow=True,
        )

    def test_import_page_loads(self, staff_client):
        url = reverse("admin:directory_practitioner_import_csv")

        assert staff_client.get(url).status_code == 200

    def test_imports_a_practitioner(self, staff_client, settings):
        settings.GOOGLE_MAPS_API_KEY = ""
        csv_text = (
            "display_name,credentials,city,region,tier,modalities,concerns\n"
            "Wei Chen,LAc,Seattle,WA,verified,"
            "Acupuncture|Herbal Medicine,Sleep problems\n"
        )

        self._upload(staff_client, csv_text, publish="on")

        created = Practitioner.objects.get(display_name="Wei Chen")
        assert created.tier == "verified"
        assert created.is_published is True
        assert {m.name for m in created.modalities.all()} == {
            "Acupuncture",
            "Herbal Medicine",
        }
        # Names that did not exist yet are created rather than silently dropped.
        assert HealthConcern.objects.filter(name="Sleep problems").exists()

    def test_import_geocodes_rows_with_no_coordinates(self, staff_client, settings):
        settings.GOOGLE_MAPS_API_KEY = ""

        self._upload(
            staff_client,
            "display_name,city\nDenver Person,Denver\n",
            geocode_missing="on",
        )

        created = Practitioner.objects.get(display_name="Denver Person")
        assert created.latitude is not None

    def test_reimporting_updates_rather_than_duplicates(self, staff_client, settings):
        settings.GOOGLE_MAPS_API_KEY = ""
        self._upload(staff_client, "display_name,city\nSame Person,Austin\n")
        self._upload(staff_client, "display_name,city\nSame Person,Denver\n")

        assert Practitioner.objects.filter(display_name="Same Person").count() == 1
        assert Practitioner.objects.get(display_name="Same Person").city == "Denver"

    def test_rows_without_a_name_are_reported_not_silently_skipped(
        self, staff_client, settings
    ):
        settings.GOOGLE_MAPS_API_KEY = ""

        response = self._upload(staff_client, "display_name,city\n,Austin\n")

        assert b"no display_name" in response.content
        assert Practitioner.objects.count() == 0

    def test_imported_listings_are_drafts_by_default(self, staff_client, settings):
        settings.GOOGLE_MAPS_API_KEY = ""

        self._upload(staff_client, "display_name,city\nDrafty,Austin\n")

        assert Practitioner.objects.get(display_name="Drafty").is_published is False


@pytest.mark.django_db
class TestUsageAdminIsReadOnly:
    def test_usage_rows_cannot_be_created_by_hand(self, staff_client):
        for model in ("dailystat", "practitionerevent", "searchquota"):
            url = reverse(f"admin:analytics_{model}_add")
            assert staff_client.get(url).status_code == 403

    def test_daily_stats_render(self, staff_client):
        DailyStat.objects.create(
            day="2026-09-01",
            searches=100,
            zero_result_searches=30,
            practitioner_impressions=250,
            practitioner_clicks=40,
        )

        response = staff_client.get(reverse("admin:analytics_dailystat_changelist"))

        assert response.status_code == 200
        assert b"30 (30%)" in response.content
        assert b"16.0%" in response.content

    def test_quota_list_shows_a_hash_not_an_address(self, staff_client):
        SearchQuota.objects.create(ip_hash="a" * 64, day="2026-09-01", search_count=3)

        response = staff_client.get(reverse("admin:analytics_searchquota_changelist"))

        assert response.status_code == 200
        assert b"aaaaaaaaaaaaaaaa" in response.content
