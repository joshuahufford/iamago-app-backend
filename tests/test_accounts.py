import pytest
from django.urls import reverse

from apps.accounts.models import Profile, User
from tests.conftest import PASSWORD


@pytest.mark.django_db
class TestRegistration:
    def test_creates_user_and_profile(self, api):
        response = api.post(
            reverse("register"),
            {
                "email": "Grace@Example.com",
                "first_name": "Grace",
                "last_name": "Hopper",
                "password": PASSWORD,
                "password_confirm": PASSWORD,
            },
            format="json",
        )

        assert response.status_code == 201
        assert response.json()["email"] == "Grace@example.com"

        created = User.objects.get(email="Grace@example.com")
        assert created.check_password(PASSWORD)
        assert Profile.objects.filter(user=created).exists()

    def test_rejects_mismatched_passwords(self, api):
        response = api.post(
            reverse("register"),
            {
                "email": "new@example.com",
                "password": PASSWORD,
                "password_confirm": "something-else",
            },
            format="json",
        )

        assert response.status_code == 400
        assert "password_confirm" in response.json()["errors"]

    def test_rejects_duplicate_email_case_insensitively(self, api, user):
        response = api.post(
            reverse("register"),
            {
                "email": user.email.upper(),
                "password": PASSWORD,
                "password_confirm": PASSWORD,
            },
            format="json",
        )

        assert response.status_code == 400
        assert "email" in response.json()["errors"]

    def test_rejects_weak_password(self, api):
        response = api.post(
            reverse("register"),
            {"email": "weak@example.com", "password": "pw", "password_confirm": "pw"},
            format="json",
        )

        assert response.status_code == 400


@pytest.mark.django_db
class TestLogin:
    def test_returns_tokens_and_user(self, api, user):
        response = api.post(
            reverse("login"),
            {"email": user.email, "password": PASSWORD},
            format="json",
        )

        assert response.status_code == 200
        body = response.json()
        assert body["access"] and body["refresh"]
        assert body["user"]["email"] == user.email

    def test_rejects_bad_credentials(self, api, user):
        response = api.post(
            reverse("login"),
            {"email": user.email, "password": "wrong"},
            format="json",
        )

        assert response.status_code == 401

    def test_access_token_authenticates_requests(self, api, user):
        token = api.post(
            reverse("login"),
            {"email": user.email, "password": PASSWORD},
            format="json",
        ).json()["access"]

        response = api.get(reverse("me"), HTTP_AUTHORIZATION=f"Bearer {token}")

        assert response.status_code == 200
        assert response.json()["email"] == user.email

    def test_refresh_returns_a_new_access_token(self, api, user):
        refresh = api.post(
            reverse("login"),
            {"email": user.email, "password": PASSWORD},
            format="json",
        ).json()["refresh"]

        response = api.post(reverse("token-refresh"), {"refresh": refresh}, format="json")

        assert response.status_code == 200
        assert "access" in response.json()


@pytest.mark.django_db
class TestMe:
    def test_requires_authentication(self, api):
        assert api.get(reverse("me")).status_code == 401

    def test_returns_profile(self, auth_api, user):
        response = auth_api.get(reverse("me"))

        assert response.status_code == 200
        body = response.json()
        assert body["full_name"] == "Ada Lovelace"
        assert body["profile"]["theme"] == "auto"

    def test_updates_user_and_nested_profile(self, auth_api, user):
        response = auth_api.patch(
            reverse("me"),
            {"first_name": "Augusta", "profile": {"theme": "dark", "bio": "Hi"}},
            format="json",
        )

        assert response.status_code == 200
        user.refresh_from_db()
        assert user.first_name == "Augusta"
        assert user.profile.theme == "dark"
        assert user.profile.bio == "Hi"

    def test_cannot_escalate_privileges(self, auth_api, user):
        auth_api.patch(reverse("me"), {"is_staff": True}, format="json")

        user.refresh_from_db()
        assert user.is_staff is False


@pytest.mark.django_db
class TestChangePassword:
    def test_changes_password(self, auth_api, user):
        response = auth_api.post(
            reverse("change-password"),
            {"current_password": PASSWORD, "new_password": "an0ther-g00d-pw"},
            format="json",
        )

        assert response.status_code == 204
        user.refresh_from_db()
        assert user.check_password("an0ther-g00d-pw")

    def test_rejects_wrong_current_password(self, auth_api, user):
        response = auth_api.post(
            reverse("change-password"),
            {"current_password": "nope", "new_password": "an0ther-g00d-pw"},
            format="json",
        )

        assert response.status_code == 400
        assert "current_password" in response.json()["errors"]


@pytest.mark.django_db
class TestUserModel:
    def test_create_superuser(self):
        admin = User.objects.create_superuser(email="root@example.com", password=PASSWORD)

        assert admin.is_staff and admin.is_superuser

    def test_email_is_required(self):
        with pytest.raises(ValueError):
            User.objects.create_user(email="", password=PASSWORD)
