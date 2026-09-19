from datetime import date, timedelta

from django.db.models import Count, Q
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.analytics.models import PractitionerEvent
from apps.analytics.services import visitor_hash
from apps.outreach.models import ContactRequest
from apps.outreach.serializers import (
    ContactRequestPortalSerializer,
    ContactRequestUpdateSerializer,
)
from apps.portal.permissions import IsClaimedPractitioner
from apps.portal.serializers import (
    PortalPractitionerSerializer,
    PortalPractitionerUpdateSerializer,
)

DEFAULT_WINDOW_DAYS = 30


class PortalPractitionerView(generics.RetrieveUpdateAPIView):
    """The signed-in practitioner's own listing."""

    permission_classes = [IsClaimedPractitioner]

    def get_object(self):
        return self.request.user.practitioner

    def get_serializer_class(self):
        if self.request.method in ("PUT", "PATCH"):
            return PortalPractitionerUpdateSerializer
        return PortalPractitionerSerializer


class PortalStatsView(APIView):
    """What the listing earned over a window — the renewal conversation.

    Impressions and clicks come from events the server recorded, so these are
    the same numbers the admin sees, not a client's account of them.
    """

    permission_classes = [IsClaimedPractitioner]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "days",
                int,
                description=f"Window length, default {DEFAULT_WINDOW_DAYS}.",
            )
        ],
        responses={200: dict},
    )
    def get(self, request):
        practitioner = request.user.practitioner
        try:
            days = max(
                1, min(int(request.query_params.get("days", DEFAULT_WINDOW_DAYS)), 365)
            )
        except (TypeError, ValueError):
            days = DEFAULT_WINDOW_DAYS

        since = date.today() - timedelta(days=days - 1)

        events = PractitionerEvent.objects.filter(
            practitioner=practitioner, created_at__date__gte=since
        ).aggregate(
            impressions=Count("id", filter=Q(kind=PractitionerEvent.Kind.IMPRESSION)),
            profile_views=Count("id", filter=Q(kind=PractitionerEvent.Kind.PROFILE)),
            phone_reveals=Count("id", filter=Q(kind=PractitionerEvent.Kind.PHONE)),
            website_clicks=Count("id", filter=Q(kind=PractitionerEvent.Kind.WEBSITE)),
        )

        contacts = ContactRequest.objects.filter(
            practitioner=practitioner, created_at__date__gte=since
        )
        contact_totals = contacts.aggregate(
            total=Count("id"),
            new=Count("id", filter=Q(status=ContactRequest.Status.NEW)),
        )

        impressions = events["impressions"] or 0
        clicks = (
            (events["profile_views"] or 0)
            + (events["phone_reveals"] or 0)
            + (events["website_clicks"] or 0)
        )

        return Response(
            {
                "days": days,
                "since": since,
                "impressions": impressions,
                "profile_views": events["profile_views"] or 0,
                "phone_reveals": events["phone_reveals"] or 0,
                "website_clicks": events["website_clicks"] or 0,
                "clicks": clicks,
                "click_through_rate": (clicks / impressions) if impressions else 0.0,
                "contact_requests": contact_totals["total"] or 0,
                "new_contact_requests": contact_totals["new"] or 0,
                "tier": practitioner.tier,
            }
        )


class PortalContactRequestListView(generics.ListAPIView):
    """Enquiries for this listing. Scoped to the signed-in practitioner."""

    serializer_class = ContactRequestPortalSerializer
    permission_classes = [IsClaimedPractitioner]

    def get_queryset(self):
        queryset = ContactRequest.objects.filter(
            practitioner=self.request.user.practitioner
        ).select_related("recommendation_request")

        requested_status = self.request.query_params.get("status")
        if requested_status:
            queryset = queryset.filter(status=requested_status)
        return queryset


class PortalContactRequestDetailView(generics.RetrieveUpdateAPIView):
    """One enquiry.

    Opening it records an access, because the record can carry why someone is
    seeking care and that is worth being able to account for afterwards.
    """

    permission_classes = [IsClaimedPractitioner]
    lookup_url_kwarg = "pk"

    def get_queryset(self):
        return ContactRequest.objects.filter(
            practitioner=self.request.user.practitioner
        ).select_related("recommendation_request")

    def get_serializer_class(self):
        if self.request.method in ("PUT", "PATCH"):
            return ContactRequestUpdateSerializer
        return ContactRequestPortalSerializer

    def retrieve(self, request, *args, **kwargs):
        contact = self.get_object()
        contact.mark_viewed(by=request.user, ip_hash=visitor_hash(request))
        return Response(ContactRequestPortalSerializer(contact).data)

    def update(self, request, *args, **kwargs):
        contact = self.get_object()
        serializer = self.get_serializer(contact, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        previous_status = contact.status
        updated = serializer.save()

        if (
            previous_status != ContactRequest.Status.RESPONDED
            and updated.status == ContactRequest.Status.RESPONDED
            and updated.responded_at is None
        ):
            from django.utils import timezone

            updated.responded_at = timezone.now()
            updated.save(update_fields=["responded_at", "updated_at"])

        return Response(
            ContactRequestPortalSerializer(updated).data, status=status.HTTP_200_OK
        )
