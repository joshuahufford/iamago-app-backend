from django.contrib import admin
from django.utils.html import format_html

from apps.directory.models import (
    HealthConcern,
    Modality,
    Practitioner,
    Recommendation,
    RecommendationRequest,
)


@admin.register(Modality)
class ModalityAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "sort_order")
    list_editable = ("is_active", "sort_order")
    search_fields = ("name", "description")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(HealthConcern)
class HealthConcernAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "sort_order")
    list_editable = ("is_active", "sort_order")
    search_fields = ("name", "description")
    filter_horizontal = ("modalities",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Practitioner)
class PractitionerAdmin(admin.ModelAdmin):
    list_display = (
        "display_name",
        "practice_name",
        "city",
        "region",
        "tier_badge",
        "is_published",
        "accepting_new_patients",
    )
    list_filter = (
        "tier",
        "is_published",
        "accepting_new_patients",
        "offers_telehealth",
        "region",
        "modalities",
    )
    search_fields = ("display_name", "practice_name", "city", "email", "bio")
    filter_horizontal = ("modalities", "concerns")
    list_select_related = ("user",)
    autocomplete_fields = ("user",)
    fieldsets = (
        (
            "Listing",
            {
                "fields": (
                    "display_name",
                    "credentials",
                    "practice_name",
                    "bio",
                    "photo_url",
                    "years_experience",
                )
            },
        ),
        (
            "Placement",
            {
                "fields": ("tier", "is_published"),
                "description": (
                    "<b>Partner</b> is a paying partner. <b>Verified</b> is our "
                    "internal flag for a practitioner we have vetted but who is "
                    "not paying. Both earn a badge; partner ranks higher. Neither "
                    "can outrank a materially better clinical match."
                ),
            },
        ),
        ("Care", {"fields": ("modalities", "concerns")}),
        (
            "Availability",
            {
                "fields": (
                    "accepting_new_patients",
                    "offers_telehealth",
                    "accepts_insurance",
                )
            },
        ),
        (
            "Location",
            {
                "fields": (
                    "address_line1",
                    "address_line2",
                    "city",
                    "region",
                    "postal_code",
                    "country",
                    "latitude",
                    "longitude",
                )
            },
        ),
        ("Contact", {"fields": ("website", "phone", "email", "user")}),
    )

    @admin.display(description="Tier", ordering="tier")
    def tier_badge(self, obj):
        colors = {"partner": "#00a69c", "verified": "#2b388f", "standard": "#808285"}
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:10px;font-size:11px">{}</span>',
            colors.get(obj.tier, "#808285"),
            obj.get_tier_display(),
        )


class RecommendationInline(admin.TabularInline):
    model = Recommendation
    extra = 0
    readonly_fields = ("practitioner", "rank", "score", "distance_km", "reasons")
    can_delete = False


@admin.register(RecommendationRequest)
class RecommendationRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "location_label", "user", "radius_km", "created_at")
    list_filter = ("include_telehealth", "accepting_new_patients_only", "created_at")
    search_fields = ("location_label", "user__email")
    filter_horizontal = ("concerns", "modalities")
    readonly_fields = ("claim_token", "created_at", "updated_at")
    inlines = (RecommendationInline,)
