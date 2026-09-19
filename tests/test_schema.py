import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_openapi_schema_generates_without_errors(api):
    response = api.get(reverse("schema"), {"format": "json"})

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/auth/login/" in paths
    assert "/api/health/" in paths
