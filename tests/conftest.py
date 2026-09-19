import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User

PASSWORD = "sup3r-s3cret-pw"


@pytest.fixture(autouse=True)
def plain_static_storage(settings):
    """Serve static files without the hashed manifest during tests.

    The production storage resolves every ``{% static %}`` through a manifest
    that only exists after ``collectstatic``. Django forces ``DEBUG=False`` in
    tests, which takes that path — so without this, rendering any admin page
    would depend on a build step having run first.
    """
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }


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
