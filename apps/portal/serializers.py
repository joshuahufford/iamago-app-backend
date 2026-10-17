from rest_framework import serializers

from apps.directory.models import Practitioner
from apps.directory.serializers import HealthConcernSerializer, ModalitySerializer


class PortalPractitionerSerializer(serializers.ModelSerializer):
    """The practitioner's own listing, as they see it.

    ``tier`` and ``is_published`` are read-only on purpose: a practitioner
    cannot promote themselves to partner or publish an unreviewed listing.
    """

    modalities = ModalitySerializer(many=True, read_only=True)
    concerns = HealthConcernSerializer(many=True, read_only=True)
    is_preferred = serializers.BooleanField(read_only=True)

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
            "offers_telehealth",
            "accepting_new_patients",
            "accepts_insurance",
            "tier",
            "is_published",
            "is_preferred",
        )
        read_only_fields = ("id", "tier", "is_published", "is_preferred")


class PortalPractitionerUpdateSerializer(serializers.ModelSerializer):
    """What a practitioner may edit about themselves.

    Location fields are included because a clinic moves; coordinates are not,
    because a wrong pair silently breaks matching. Re-geocoding is an admin
    action instead.
    """

    modalities = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Practitioner.modalities.rel.model.objects.filter(is_active=True),
    )
    concerns = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Practitioner.concerns.rel.model.objects.filter(is_active=True)
    )

    class Meta:
        model = Practitioner
        fields = (
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
            "offers_telehealth",
            "accepting_new_patients",
            "accepts_insurance",
        )

    def update(self, instance, validated_data):
        """Write only the columns this serializer owns.

        The default implementation saves the whole instance, which would also
        rewrite fields a practitioner must not control — tier, publication
        state, coordinates — from whatever the in-memory copy happened to hold.
        That silently clobbers a concurrent admin change.
        """
        modalities = validated_data.pop("modalities", None)
        concerns = validated_data.pop("concerns", None)

        for field, value in validated_data.items():
            setattr(instance, field, value)
        if validated_data:
            instance.save(update_fields=[*validated_data, "updated_at"])

        if modalities is not None:
            instance.modalities.set(modalities)
        if concerns is not None:
            instance.concerns.set(concerns)

        return instance

    def to_representation(self, instance):
        return PortalPractitionerSerializer(instance, context=self.context).data
