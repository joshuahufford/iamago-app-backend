from rest_framework import serializers

from apps.directory.models import RecommendationRequest
from apps.directory.serializers import HealthConcernSerializer, ModalitySerializer
from apps.outreach.models import ContactRequest


class SavedSearchSerializer(serializers.ModelSerializer):
    """One past search, summarised for a list.

    Carries the practitioner names rather than the whole card: the dashboard is
    for recognising a search you already ran, and the full results are one click
    away behind the existing shareable link.
    """

    concerns = HealthConcernSerializer(many=True, read_only=True)
    modalities = ModalitySerializer(many=True, read_only=True)
    practitioner_names = serializers.SerializerMethodField()

    class Meta:
        model = RecommendationRequest
        fields = (
            "id",
            "claim_token",
            "location_label",
            "radius_miles",
            "concerns",
            "modalities",
            "result_count",
            "practitioner_names",
            "created_at",
        )

    def get_practitioner_names(self, obj):
        return [
            recommendation.practitioner.display_name
            for recommendation in obj.recommendations.all()
        ]


class SavedEnquirySerializer(serializers.ModelSerializer):
    """An enquiry the patient sent, from their side.

    Deliberately excludes ``practitioner_note`` — that note is the
    practitioner's private working record, not correspondence.
    """

    practitioner_name = serializers.CharField(
        source="practitioner.display_name", read_only=True
    )
    practitioner_id = serializers.UUIDField(source="practitioner.id", read_only=True)

    class Meta:
        model = ContactRequest
        fields = (
            "id",
            "practitioner_id",
            "practitioner_name",
            "status",
            "share_concerns",
            "consent_text",
            "message",
            "first_viewed_at",
            "responded_at",
            "created_at",
        )


class ClaimSearchSerializer(serializers.Serializer):
    """Attach a search made before signing up to the account that made it."""

    id = serializers.UUIDField()
    token = serializers.CharField()
