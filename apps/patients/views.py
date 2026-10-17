import hmac

from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.directory.models import RecommendationRequest
from apps.outreach.models import ContactRequest
from apps.patients.serializers import (
    ClaimSearchSerializer,
    SavedEnquirySerializer,
    SavedSearchSerializer,
)


class SavedSearchListView(generics.ListAPIView):
    """Searches this patient has run or claimed."""

    serializer_class = SavedSearchSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            RecommendationRequest.objects.filter(user=self.request.user)
            .prefetch_related("concerns", "modalities", "recommendations__practitioner")
            .order_by("-created_at")
        )


class SavedEnquiryListView(generics.ListAPIView):
    """Enquiries this patient has sent."""

    serializer_class = SavedEnquirySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            ContactRequest.objects.filter(patient=self.request.user)
            .select_related("practitioner")
            .order_by("-created_at")
        )


class ClaimSearchView(APIView):
    """Attach an anonymous search to the signed-in account.

    The homepage works without an account by design, so almost every patient's
    first searches are anonymous. Without this their dashboard would be empty
    however much they had used the site.

    The claim token is the capability — the same one that opens the results —
    and only an unclaimed search can be taken, so claiming can never move a
    search away from the account that already holds it.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(request=ClaimSearchSerializer, responses={200: SavedSearchSerializer})
    def post(self, request):
        serializer = ClaimSearchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        search = RecommendationRequest.objects.filter(
            pk=serializer.validated_data["id"]
        ).first()

        # A wrong token reads as "not found" so this cannot be used to probe
        # which search ids exist.
        if search is None or not hmac.compare_digest(
            search.claim_token, serializer.validated_data["token"]
        ):
            return Response(
                {"detail": "Not found.", "errors": {}},
                status=status.HTTP_404_NOT_FOUND,
            )

        if search.user_id is not None:
            if search.user_id == request.user.id:
                return Response(SavedSearchSerializer(search).data)
            return Response(
                {
                    "detail": "That search is already saved to another account.",
                    "errors": {},
                },
                status=status.HTTP_409_CONFLICT,
            )

        search.user = request.user
        search.save(update_fields=["user", "updated_at"])
        return Response(SavedSearchSerializer(search).data)
