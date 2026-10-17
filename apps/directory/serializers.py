import secrets

from django.db import transaction
from rest_framework import serializers

from apps.analytics.models import PractitionerEvent
from apps.analytics.services import visitor_hash
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
        fields = ("rank", "score", "distance_miles", "reasons", "practitioner")


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
            "radius_miles",
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
    radius_miles = serializers.IntegerField(required=False, min_value=1, max_value=300)
    include_telehealth = serializers.BooleanField(required=False, default=True)
    accepting_new_patients_only = serializers.BooleanField(required=False, default=False)
    # Only required once the anonymous daily allowance is spent; the view
    # enforces that, so it stays optional here.
    email = serializers.EmailField(required=False, allow_blank=True)

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
            email=validated_data.get("email", ""),
            ip_hash=visitor_hash(request) if request else "",
            user_agent=(request.META.get("HTTP_USER_AGENT", "")[:400] if request else ""),
            location_label=validated_data.get("location_label", ""),
            latitude=validated_data["latitude"],
            longitude=validated_data["longitude"],
            radius_miles=validated_data.get("radius_miles", 25),
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
            radius_miles=float(recommendation_request.radius_miles),
            include_telehealth=recommendation_request.include_telehealth,
            accepting_new_patients_only=(
                recommendation_request.accepting_new_patients_only
            ),
        )

        results = recommend(criteria, limit=MAX_RESULTS)
        Recommendation.objects.bulk_create(
            Recommendation(
                request=recommendation_request,
                practitioner=result.practitioner,
                rank=index,
                score=result.score,
                distance_miles=result.distance_miles,
                reasons=result.reasons,
            )
            for index, result in enumerate(results, start=1)
        )

        recommendation_request.result_count = len(results)
        recommendation_request.save(update_fields=["result_count"])

        # Impressions are written here rather than reported by the browser, so
        # a partner's numbers cannot be inflated by a client.
        PractitionerEvent.objects.bulk_create(
            PractitionerEvent(
                practitioner=result.practitioner,
                request=recommendation_request,
                kind=PractitionerEvent.Kind.IMPRESSION,
                tier_at_event=result.practitioner.tier,
            )
            for result in results
        )

        return recommendation_request

    def to_representation(self, instance):
        return RecommendationRequestSerializer(instance, context=self.context).data


class PractitionerEventSerializer(serializers.Serializer):
    """A click-through reported by the browser."""

    practitioner = serializers.PrimaryKeyRelatedField(
        queryset=Practitioner.objects.filter(is_published=True)
    )
    kind = serializers.ChoiceField(
        choices=[
            PractitionerEvent.Kind.PROFILE,
            PractitionerEvent.Kind.PHONE,
            PractitionerEvent.Kind.WEBSITE,
        ]
    )
    request_id = serializers.PrimaryKeyRelatedField(
        queryset=RecommendationRequest.objects.all(),
        required=False,
        allow_null=True,
    )

    def create(self, validated_data):
        practitioner = validated_data["practitioner"]
        return PractitionerEvent.objects.create(
            practitioner=practitioner,
            request=validated_data.get("request_id"),
            kind=validated_data["kind"],
            tier_at_event=practitioner.tier,
        )
