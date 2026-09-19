from django.db import transaction
from rest_framework import serializers

from apps.analytics.services import visitor_hash
from apps.directory.models import Practitioner, RecommendationRequest
from apps.directory.serializers import HealthConcernSerializer
from apps.outreach.models import ContactRequest

# Shown to the patient and stored verbatim on the record. Changing this changes
# what future patients agree to; it does not rewrite what past ones agreed to.
CONSENT_TEXT = (
    "I agree that iamago may share my name and contact details with this "
    "practitioner so they can get in touch with me about care."
)
CONSENT_TEXT_WITH_CONCERNS = (
    "I agree that iamago may share my name, contact details and the health "
    "concerns I selected with this practitioner so they can get in touch with "
    "me about care."
)


class ContactRequestCreateSerializer(serializers.ModelSerializer):
    """A patient asking to be contacted.

    Consent is recorded as the exact wording shown, so the stored record says
    what the person actually agreed to rather than that a box was ticked.
    """

    practitioner = serializers.PrimaryKeyRelatedField(
        queryset=Practitioner.objects.filter(is_published=True)
    )
    recommendation_request = serializers.PrimaryKeyRelatedField(
        queryset=RecommendationRequest.objects.all(), required=False, allow_null=True
    )
    consent = serializers.BooleanField(write_only=True)

    class Meta:
        model = ContactRequest
        fields = (
            "id",
            "practitioner",
            "recommendation_request",
            "name",
            "email",
            "phone",
            "message",
            "share_concerns",
            "consent",
            "created_at",
        )
        read_only_fields = ("id", "created_at")

    def validate_consent(self, value):
        if not value:
            raise serializers.ValidationError(
                "We can only pass your details on if you agree to it."
            )
        return value

    def validate_name(self, value):
        if not value.strip():
            raise serializers.ValidationError("Tell the practitioner who is asking.")
        return value.strip()

    @transaction.atomic
    def create(self, validated_data):
        validated_data.pop("consent")
        request = self.context.get("request")
        user = request.user if request and request.user.is_authenticated else None
        share_concerns = validated_data.get("share_concerns", False)

        return ContactRequest.objects.create(
            patient=user,
            consent_text=(CONSENT_TEXT_WITH_CONCERNS if share_concerns else CONSENT_TEXT),
            ip_hash=visitor_hash(request) if request else "",
            **validated_data,
        )


class ContactRequestPatientSerializer(serializers.ModelSerializer):
    """What the patient sees back after asking. Deliberately thin."""

    practitioner_name = serializers.CharField(
        source="practitioner.display_name", read_only=True
    )

    class Meta:
        model = ContactRequest
        fields = ("id", "practitioner_name", "created_at")


class ContactRequestPortalSerializer(serializers.ModelSerializer):
    """What a practitioner sees in their portal.

    ``concerns`` is empty unless the patient agreed to share it — the model
    enforces that, rather than leaving it to every caller to remember.
    """

    concerns = serializers.SerializerMethodField()
    search_location = serializers.SerializerMethodField()

    class Meta:
        model = ContactRequest
        fields = (
            "id",
            "name",
            "email",
            "phone",
            "message",
            "concerns",
            "search_location",
            "share_concerns",
            "status",
            "practitioner_note",
            "first_viewed_at",
            "responded_at",
            "created_at",
        )
        read_only_fields = fields

    def get_concerns(self, obj):
        return HealthConcernSerializer(obj.shared_concerns, many=True).data

    def get_search_location(self, obj):
        if obj.recommendation_request_id is None:
            return ""
        return obj.recommendation_request.location_label


class ContactRequestUpdateSerializer(serializers.ModelSerializer):
    """The only fields a practitioner may change on a request."""

    class Meta:
        model = ContactRequest
        fields = ("status", "practitioner_note")

    def validate_status(self, value):
        if value == ContactRequest.Status.NEW:
            raise serializers.ValidationError("A request cannot be moved back to new.")
        return value
