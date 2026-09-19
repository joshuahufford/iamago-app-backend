import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User

PASSWORD = "sup3r-s3cret-pw"


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        email="ada@example.com",
        password=PASSWORD,
        first_name="Ada",
        last_name="Lovelace",
    )


@pytest.fixture
def auth_api(api, user):
    api.force_authenticate(user=user)
    return api
