import pytest
from django.db.utils import OperationalError
from django.urls import reverse


@pytest.mark.django_db
def test_health_is_public_and_reports_database(api):
    response = api.get(reverse("health"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


@pytest.mark.django_db
def test_health_reports_503_when_the_database_is_unreachable(api, monkeypatch):
    def explode(*args, **kwargs):
        raise OperationalError("connection refused")

    monkeypatch.setattr("django.db.connection.cursor", explode)

    response = api.get(reverse("health"))

    assert response.status_code == 503
    assert response.json() == {"status": "error", "database": "unavailable"}
