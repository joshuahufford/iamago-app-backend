from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.analytics.services import check_contact_quota, record_block
from apps.directory.models import RecommendationRequest
from apps.outreach.serializers import (
    ContactRequestCreateSerializer,
    ContactRequestPatientSerializer,
)
from apps.outreach.services import email_recommendations, notify_contact_request


class ContactRequestCreateView(generics.CreateAPIView):
    """A patient asking a practitioner to get in touch.

    Public, because the whole flow works without an account. Metered on the
    same per-visitor allowance as search, so the contact form cannot be used to
    spam practitioners once the search limit is reached.
    """

    serializer_class = ContactRequestCreateSerializer
    permission_classes = [AllowAny]
    # Authentication stays on: an enquiry sent while signed in has to be linked
    # to that account, or the patient can never follow it up.

    def create(self, request, *args, **kwargs):
        verdict = check_contact_quota(request)
        if not verdict.allowed:
            record_block(request)
            return Response(
                {
                    "detail": (
                        "You have sent as many enquiries as we allow in a day. "
                        "Try again tomorrow."
                    ),
                    "errors": {},
                    "code": verdict.code,
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        contact = serializer.save()

        # After the row is safely saved: a mail failure must not lose it.
        notify_contact_request(contact)

        return Response(
            ContactRequestPatientSerializer(contact).data,
            status=status.HTTP_201_CREATED,
        )


class EmailRecommendationsView(APIView):
    """Send a visitor their own matches, by claim token.

    The token is what authorises it, so nobody can have someone else's results
    mailed anywhere — and the address is not stored beyond the send.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(request=None, responses={204: None, 404: None})
    def post(self, request, pk):
        import hmac

        token = (request.data.get("token") or "").strip()
        email = (request.data.get("email") or "").strip()

        recommendation_request = RecommendationRequest.objects.filter(pk=pk).first()
        if (
            recommendation_request is None
            or not token
            or not hmac.compare_digest(recommendation_request.claim_token, token)
        ):
            return Response(
                {"detail": "Not found.", "errors": {}},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not email:
            return Response(
                {
                    "detail": "Where should we send them?",
                    "errors": {"email": ["Required."]},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        email_recommendations(recommendation_request, email)
        return Response(status=status.HTTP_204_NO_CONTENT)
