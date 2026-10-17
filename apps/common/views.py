from django.db import connection
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthView(APIView):
    """Liveness/readiness probe, including a database round-trip."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(
        responses={200: dict, 503: dict},
        description="Returns service and database status.",
    )
    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except Exception:  # pragma: no cover - only hit when the DB is down
            return Response(
                {"status": "error", "database": "unavailable"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response({"status": "ok", "database": "ok"})
