import secrets

from django.db import transaction
from rest_framework import serializers

from apps.directory.matching import MAX_RESULTS, MatchCriteria, recommend
from apps.directory.models import (
    HealthConcern,
    Modality,
    Practitioner,
    Recommendation,
    RecommendationRequest,
)


class ModalitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Modality
        fields = ("id", "name", "slug", "description")


class HealthConcernSerializer(serializers.ModelSerializer):
    modalities = serializers.SlugRelatedField(
        many=True, read_only=True, slug_field="slug"
    )

    class Meta:
        model = HealthConcern
        fields = ("id", "name", "slug", "description", "modalities")


class PractitionerSerializer(serializers.ModelSerializer):
    """Public-facing practitioner card.

    Contact details are included because the directory's whole purpose is to
    connect patients with providers; anything not meant to be public simply is
    not listed here.
    """

    modalities = ModalitySerializer(many=True, read_only=True)
    concerns = HealthConcernSerializer(many=True, read_only=True)
    is_preferred = serializers.BooleanField(read_only=True)
    latitude = serializers.FloatField(read_only=True)
    longitude = serializers.FloatField(read_only=True)

    class Meta:
        model = Practitioner
        fields = (
            "id",
            "display_name",
            "credentials",
            "practice_name",
            "bio",
            "photo_url",
            "website",
            "phone",
            "email",
            "years_experience",
            "modalities",
            "concerns",
            "address_line1",
            "address_line2",
            "city",
            "region",
            "postal_code",
            "country",
            "latitude",
            "longitude",
            "offers_telehealth",
            "accepting_new_patients",
            "accepts_insurance",
            "tier",
            "is_preferred",
        )


class RecommendationSerializer(serializers.ModelSerializer):
    practitioner = PractitionerSerializer(read_only=True)

    class Meta:
        model = Recommendation
        fields = ("rank", "score", "distance_km", "reasons", "practitioner")


class RecommendationRequestSerializer(serializers.ModelSerializer):
    """Read view of a completed quiz run and its results."""

    recommendations = RecommendationSerializer(many=True, read_only=True)
    concerns = HealthConcernSerializer(many=True, read_only=True)
    modalities = ModalitySerializer(many=True, read_only=True)
    latitude = serializers.FloatField(read_only=True)
    longitude = serializers.FloatField(read_only=True)

    class Meta:
        model = RecommendationRequest
        fields = (
            "id",
            "claim_token",
            "concerns",
            "modalities",
            "location_label",
            "latitude",
            "longitude",
            "radius_km",
            "include_telehealth",
            "accepting_new_patients_only",
            "created_at",
            "recommendations",
        )


class RecommendationRequestCreateSerializer(serializers.Serializer):
    """Input from the homepage quiz.

    Location is accepted either as coordinates (from the Google Places
    autocomplete in the browser) or as free text we geocode server-side, so the
    flow still works when the client has no Maps key.
    """

    concerns = serializers.PrimaryKeyRelatedField(
        many=True, queryset=HealthConcern.objects.filter(is_active=True), required=False
    )
    modalities = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Modality.objects.filter(is_active=True), required=False
    )
    location_label = serializers.CharField(required=False, allow_blank=True)
    latitude = serializers.FloatField(required=False, allow_null=True)
    longitude = serializers.FloatField(required=False, allow_null=True)
    radius_km = serializers.IntegerField(required=False, min_value=1, max_value=500)
    include_telehealth = serializers.BooleanField(required=False, default=True)
    accepting_new_patients_only = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        if not attrs.get("concerns") and not attrs.get("modalities"):
            raise serializers.ValidationError(
                "Tell us at least one concern or one type of care you are looking for."
            )

        has_coords = (
            attrs.get("latitude") is not None and attrs.get("longitude") is not None
        )
        if not has_coords and not attrs.get("location_label"):
            raise serializers.ValidationError(
                {"location_label": "Enter a city or postal code, or share your location."}
            )

        if not has_coords:
            from apps.directory.geocoding import geocode

            result = geocode(attrs["location_label"])
            if result is None:
                raise serializers.ValidationError(
                    {"location_label": "We could not find that place. Try a nearby city."}
                )
            attrs["latitude"] = result.latitude
            attrs["longitude"] = result.longitude
            attrs["location_label"] = result.label

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        concerns = validated_data.pop("concerns", [])
        modalities = validated_data.pop("modalities", [])
        request = self.context.get("request")
        user = request.user if request and request.user.is_authenticated else None

        recommendation_request = RecommendationRequest.objects.create(
            user=user,
            claim_token=secrets.token_urlsafe(32),
            location_label=validated_data.get("location_label", ""),
            latitude=validated_data["latitude"],
            longitude=validated_data["longitude"],
            radius_km=validated_data.get("radius_km", 40),
            include_telehealth=validated_data.get("include_telehealth", True),
            accepting_new_patients_only=validated_data.get(
                "accepting_new_patients_only", False
            ),
        )
        recommendation_request.concerns.set(concerns)
        recommendation_request.modalities.set(modalities)

        criteria = MatchCriteria(
            concern_ids={c.id for c in concerns},
            modality_ids={m.id for m in modalities},
            latitude=float(recommendation_request.latitude),
            longitude=float(recommendation_request.longitude),
            radius_km=float(recommendation_request.radius_km),
            include_telehealth=recommendation_request.include_telehealth,
            accepting_new_patients_only=(
                recommendation_request.accepting_new_patients_only
            ),
        )

        Recommendation.objects.bulk_create(
            Recommendation(
                request=recommendation_request,
                practitioner=result.practitioner,
                rank=index,
                score=result.score,
                distance_km=result.distance_km,
                reasons=result.reasons,
            )
            for index, result in enumerate(
                recommend(criteria, limit=MAX_RESULTS), start=1
            )
        )

        return recommendation_request

    def to_representation(self, instance):
        return RecommendationRequestSerializer(instance, context=self.context).data
