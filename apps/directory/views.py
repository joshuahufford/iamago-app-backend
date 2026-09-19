from django.conf import settings
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.analytics.services import check_quota, record_block
from apps.directory.geocoding import geocode
from apps.directory.models import (
    HealthConcern,
    Modality,
    Practitioner,
    RecommendationRequest,
)
from apps.directory.serializers import (
    HealthConcernSerializer,
    ModalitySerializer,
    PractitionerEventSerializer,
    PractitionerSerializer,
    RecommendationRequestCreateSerializer,
    RecommendationRequestSerializer,
)


class ModalityListView(generics.ListAPIView):
    """Options for the "what kind of care" step. Public by design."""

    serializer_class = ModalitySerializer
    permission_classes = [AllowAny]
    authentication_classes: list = []
    queryset = Modality.objects.filter(is_active=True)
    pagination_class = None


class HealthConcernListView(generics.ListAPIView):
    """Options for the "what brings you here" step. Public by design."""

    serializer_class = HealthConcernSerializer
    permission_classes = [AllowAny]
    authentication_classes: list = []
    queryset = HealthConcern.objects.filter(is_active=True).prefetch_related("modalities")
    pagination_class = None


class PractitionerDetailView(generics.RetrieveAPIView):
    serializer_class = PractitionerSerializer
    permission_classes = [AllowAny]
    authentication_classes: list = []
    queryset = Practitioner.objects.filter(is_published=True).prefetch_related(
        "modalities", "concerns"
    )


class RecommendationRequestCreateView(generics.CreateAPIView):
    """Run the quiz and return at most three practitioners.

    Anonymous access is intentional: the homepage flow must work before anyone
    signs up. The response carries a ``claim_token`` the visitor can use to
    attach this run to an account later.

    A per-visitor daily allowance keeps the directory from being walked. The
    first few searches are free and invisible; past that we ask for an email,
    which raises the ceiling without removing it.
    """

    serializer_class = RecommendationRequestCreateSerializer
    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(
        responses={
            201: RecommendationRequestSerializer,
            429: OpenApiResponse(
                description=(
                    "Daily allowance spent. `code` is `email_required` when an "
                    "email would raise the limit, or `rate_limited` when even "
                    "the email-backed allowance is gone."
                )
            ),
        }
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        # Checked before validation so a refused request does no real work.
        email = (request.data.get("email") or "").strip()
        verdict = check_quota(request, email=email)

        if not verdict.allowed:
            record_block(request)
            return Response(
                {
                    "detail": (
                        "You have used your free searches for today. Add your "
                        "email to keep going."
                        if verdict.code == "email_required"
                        else "You have reached today's search limit. Try again tomorrow."
                    ),
                    "errors": {},
                    "code": verdict.code,
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        response = super().create(request, *args, **kwargs)
        response["X-Search-Remaining"] = str(verdict.remaining)
        return response


class RecommendationRequestDetailView(APIView):
    """Re-open a previous run using its id and claim token."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "token",
                str,
                required=True,
                description="The claim_token returned when the request was created.",
            )
        ],
        responses={200: RecommendationRequestSerializer},
    )
    def get(self, request, pk):
        token = request.query_params.get("token", "")
        recommendation_request = (
            RecommendationRequest.objects.filter(pk=pk)
            .prefetch_related(
                "concerns",
                "modalities",
                "recommendations__practitioner__modalities",
                "recommendations__practitioner__concerns",
            )
            .first()
        )
        # A wrong or missing token is reported as "not found" rather than
        # "forbidden", so the endpoint cannot be used to confirm that a given
        # request id exists.
        if recommendation_request is None or not _token_matches(
            recommendation_request, token
        ):
            return Response(
                {"detail": "Not found.", "errors": {}},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(RecommendationRequestSerializer(recommendation_request).data)


def _token_matches(recommendation_request, token: str) -> bool:
    import hmac

    if not token or not recommendation_request.claim_token:
        return False
    return hmac.compare_digest(recommendation_request.claim_token, token)


class GeocodeView(APIView):
    """Resolve a typed place to coordinates for the location step."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(
        parameters=[OpenApiParameter("q", str, required=True)],
        responses={200: dict, 404: dict},
    )
    def get(self, request):
        result = geocode(request.query_params.get("q", ""))
        if result is None:
            return Response(
                {"detail": "We could not find that place.", "errors": {}},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(
            {
                "label": result.label,
                "latitude": result.latitude,
                "longitude": result.longitude,
                "source": result.source,
            }
        )


class MapConfigView(APIView):
    """Tells the frontend whether a Google Maps key is available.

    The browser key is public by nature (it ships in the bundle), so serving it
    here rather than baking it in at build time means one place to rotate it.
    Restrict it by HTTP referrer in the Google Cloud console.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(responses={200: dict})
    def get(self, request):
        key = getattr(settings, "GOOGLE_MAPS_BROWSER_KEY", "")
        return Response({"google_maps_api_key": key, "maps_enabled": bool(key)})


class PractitionerEventView(APIView):
    """Record a click-through on a recommended practitioner.

    Impressions are written server-side when the recommendation is made; only
    clicks need reporting from the browser, because only the browser knows
    about them. Unknown practitioners are rejected so the table cannot be
    filled with noise.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(request=PractitionerEventSerializer, responses={204: None})
    def post(self, request):
        serializer = PractitionerEventSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(status=status.HTTP_204_NO_CONTENT)
