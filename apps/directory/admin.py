import csv
import io

from django import forms
from django.contrib import admin, messages
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from apps.directory.geocoding import geocode
from apps.directory.models import (
    HealthConcern,
    Modality,
    Practitioner,
    Recommendation,
    RecommendationRequest,
)

admin.site.site_header = "iamago administration"
admin.site.site_title = "iamago admin"
admin.site.index_title = "Directory and usage"


@admin.register(Modality)
class ModalityAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "practitioner_count",
        "concern_count",
        "is_active",
        "sort_order",
    )
    list_editable = ("is_active", "sort_order")
    list_display_links = ("name",)
    search_fields = ("name", "description")
    prepopulated_fields = {"slug": ("name",)}
    fields = ("name", "slug", "description", "is_active", "sort_order")
    save_on_top = True

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .annotate(
                _practitioners=Count("practitioners", distinct=True),
                _concerns=Count("concerns", distinct=True),
            )
        )

    @admin.display(description="Practitioners", ordering="_practitioners")
    def practitioner_count(self, obj):
        return obj._practitioners

    @admin.display(description="Linked concerns", ordering="_concerns")
    def concern_count(self, obj):
        return obj._concerns


@admin.register(HealthConcern)
class HealthConcernAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "modality_list",
        "practitioner_count",
        "is_active",
        "sort_order",
    )
    list_editable = ("is_active", "sort_order")
    list_display_links = ("name",)
    search_fields = ("name", "description")
    filter_horizontal = ("modalities",)
    prepopulated_fields = {"slug": ("name",)}
    save_on_top = True
    fieldsets = (
        (None, {"fields": ("name", "slug", "description")}),
        (
            "Matching",
            {
                "fields": ("modalities",),
                "description": (
                    "Approaches typically used for this concern. These are what the "
                    "engine falls back to when a patient names a concern but no "
                    "preferred approach — so an empty list weakens matching."
                ),
            },
        ),
        ("Display", {"fields": ("is_active", "sort_order")}),
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .prefetch_related("modalities")
            .annotate(_practitioners=Count("practitioners", distinct=True))
        )

    @admin.display(description="Treated with")
    def modality_list(self, obj):
        names = [m.name for m in obj.modalities.all()]
        if not names:
            return format_html('<span style="color:#b91c1c">none set</span>')
        return ", ".join(names)

    @admin.display(description="Practitioners", ordering="_practitioners")
    def practitioner_count(self, obj):
        return obj._practitioners


class PractitionerCsvImportForm(forms.Form):
    csv_file = forms.FileField(
        label="CSV file",
        help_text="Columns: display_name, credentials, practice_name, city, region, "
        "postal_code, phone, email, website, modalities, concerns, tier, "
        "offers_telehealth, latitude, longitude. Only display_name is required.",
    )
    publish = forms.BooleanField(
        required=False,
        initial=False,
        label="Publish imported listings immediately",
        help_text="Leave off to import as drafts and review before they go live.",
    )
    geocode_missing = forms.BooleanField(
        required=False,
        initial=True,
        label="Look up coordinates where none are given",
    )


@admin.register(Practitioner)
class PractitionerAdmin(admin.ModelAdmin):
    list_display = (
        "display_name",
        "practice_name",
        "location",
        "tier_badge",
        "referrals",
        "readiness",
        "is_published",
        "accepting_new_patients",
    )
    list_editable = ("is_published", "accepting_new_patients")
    list_display_links = ("display_name",)
    list_filter = (
        "tier",
        "is_published",
        "accepting_new_patients",
        "offers_telehealth",
        "accepts_insurance",
        "region",
        "modalities",
    )
    search_fields = ("display_name", "practice_name", "city", "email", "phone", "bio")
    filter_horizontal = ("modalities", "concerns")
    autocomplete_fields = ("user",)
    save_on_top = True
    save_as = True
    list_per_page = 50
    actions = (
        "action_publish",
        "action_unpublish",
        "action_geocode",
        "action_mark_partner",
        "action_mark_verified",
        "action_mark_standard",
        "action_export_csv",
    )
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
                "description": mark_safe(
                    "<b>Partner</b> is a paying partner. <b>Verified</b> is the "
                    "internal flag for someone vetted but not paying. Both earn a "
                    "badge; partner ranks higher. Neither can outrank a materially "
                    "better clinical match."
                ),
            },
        ),
        (
            "Care",
            {
                "fields": ("modalities", "concerns"),
                "description": (
                    "A listing with no concerns will almost never be recommended — "
                    "concerns are the strongest matching signal."
                ),
            },
        ),
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
                    ("latitude", "longitude"),
                ),
                "description": (
                    "Coordinates drive distance. Save the address, then use the "
                    "<i>Look up coordinates</i> action from the list if you do not "
                    "have them to hand."
                ),
            },
        ),
        ("Contact", {"fields": ("website", "phone", "email", "user")}),
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .prefetch_related("modalities", "concerns")
            .annotate(
                _impressions=Count(
                    "events", filter=Q(events__kind="impression"), distinct=True
                ),
                _clicks=Count(
                    "events", filter=~Q(events__kind="impression"), distinct=True
                ),
            )
        )

    @admin.display(description="Where", ordering="city")
    def location(self, obj):
        parts = [p for p in (obj.city, obj.region) if p]
        return ", ".join(parts) or "—"

    @admin.display(description="Tier", ordering="tier")
    def tier_badge(self, obj):
        colors = {"partner": "#00a69c", "verified": "#2b388f", "standard": "#9ca3af"}
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:10px;font-size:11px;white-space:nowrap">{}</span>',
            colors.get(obj.tier, "#9ca3af"),
            obj.get_tier_display(),
        )

    @admin.display(description="Referrals")
    def referrals(self, obj):
        """Impressions and click-throughs — what a partner is paying for."""
        return format_html(
            "{} shown &middot; <b>{}</b> clicked", obj._impressions, obj._clicks
        )

    @admin.display(description="Ready?")
    def readiness(self, obj):
        """What is stopping this listing from being recommended."""
        missing = []
        if not obj.has_location:
            missing.append("coordinates")
        if not obj.concerns.exists():
            missing.append("concerns")
        if not obj.modalities.exists():
            missing.append("approaches")

        if not missing:
            return format_html('<span style="color:#047857">&#10003; ready</span>')
        return format_html(
            '<span style="color:#b45309" title="Cannot be matched without these">'
            "needs {}</span>",
            ", ".join(missing),
        )

    # --- Actions ------------------------------------------------------------

    @admin.action(description="Publish selected listings")
    def action_publish(self, request, queryset):
        incomplete = [p.display_name for p in queryset if not p.has_location]
        updated = queryset.update(is_published=True)
        self.message_user(request, f"Published {updated} listing(s).", messages.SUCCESS)
        if incomplete:
            self.message_user(
                request,
                "These have no coordinates and will only match by telehealth: "
                + ", ".join(incomplete),
                messages.WARNING,
            )

    @admin.action(description="Unpublish selected listings")
    def action_unpublish(self, request, queryset):
        updated = queryset.update(is_published=False)
        self.message_user(request, f"Unpublished {updated} listing(s).", messages.SUCCESS)

    @admin.action(description="Look up coordinates from address")
    def action_geocode(self, request, queryset):
        found = failed = 0
        for practitioner in queryset:
            address = ", ".join(
                part
                for part in (
                    practitioner.address_line1,
                    practitioner.city,
                    practitioner.region,
                    practitioner.postal_code,
                )
                if part
            )
            result = geocode(address) if address else None
            if result is None:
                failed += 1
                continue
            practitioner.latitude = result.latitude
            practitioner.longitude = result.longitude
            practitioner.save(update_fields=["latitude", "longitude"])
            found += 1

        if found:
            self.message_user(
                request, f"Located {found} practitioner(s).", messages.SUCCESS
            )
        if failed:
            self.message_user(
                request,
                f"Could not locate {failed}. Add a city, or enter coordinates by hand.",
                messages.WARNING,
            )

    @admin.action(description="Set tier: Partner (paying)")
    def action_mark_partner(self, request, queryset):
        self._set_tier(request, queryset, Practitioner.Tier.PARTNER)

    @admin.action(description="Set tier: Verified (vetted, unpaid)")
    def action_mark_verified(self, request, queryset):
        self._set_tier(request, queryset, Practitioner.Tier.VERIFIED)

    @admin.action(description="Set tier: Standard")
    def action_mark_standard(self, request, queryset):
        self._set_tier(request, queryset, Practitioner.Tier.STANDARD)

    def _set_tier(self, request, queryset, tier):
        updated = queryset.update(tier=tier)
        self.message_user(
            request, f"Set {updated} listing(s) to {tier}.", messages.SUCCESS
        )

    @admin.action(description="Export selected to CSV")
    def action_export_csv(self, request, queryset):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="practitioners.csv"'
        writer = csv.writer(response)
        writer.writerow(CSV_COLUMNS)
        for practitioner in queryset.prefetch_related("modalities", "concerns"):
            writer.writerow(
                [
                    practitioner.display_name,
                    practitioner.credentials,
                    practitioner.practice_name,
                    practitioner.city,
                    practitioner.region,
                    practitioner.postal_code,
                    practitioner.phone,
                    practitioner.email,
                    practitioner.website,
                    "|".join(m.name for m in practitioner.modalities.all()),
                    "|".join(c.name for c in practitioner.concerns.all()),
                    practitioner.tier,
                    practitioner.offers_telehealth,
                    practitioner.latitude or "",
                    practitioner.longitude or "",
                ]
            )
        return response

    # --- Bulk import --------------------------------------------------------

    def get_urls(self):
        return [
            path(
                "import-csv/",
                self.admin_site.admin_view(self.import_csv_view),
                name="directory_practitioner_import_csv",
            ),
        ] + super().get_urls()

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["import_csv_url"] = reverse(
            "admin:directory_practitioner_import_csv"
        )
        return super().changelist_view(request, extra_context)

    def import_csv_view(self, request):
        """Bulk-add practitioners from a spreadsheet export.

        Matching is by ``display_name``, so re-importing a corrected file
        updates the existing rows rather than duplicating them.
        """
        if request.method == "POST":
            form = PractitionerCsvImportForm(request.POST, request.FILES)
            if form.is_valid():
                created, updated, errors = self._import_rows(
                    form.cleaned_data["csv_file"],
                    publish=form.cleaned_data["publish"],
                    geocode_missing=form.cleaned_data["geocode_missing"],
                )
                self.message_user(
                    request,
                    f"Imported {created} new and updated {updated} existing listing(s).",
                    messages.SUCCESS,
                )
                for error in errors[:10]:
                    self.message_user(request, error, messages.WARNING)
                return redirect("admin:directory_practitioner_changelist")
        else:
            form = PractitionerCsvImportForm()

        context = {
            **self.admin_site.each_context(request),
            "title": "Import practitioners from CSV",
            "form": form,
            "columns": CSV_COLUMNS,
            "opts": self.model._meta,
        }
        return TemplateResponse(
            request, "admin/directory/practitioner_import.html", context
        )

    def _import_rows(self, uploaded, *, publish: bool, geocode_missing: bool):
        decoded = io.StringIO(uploaded.read().decode("utf-8-sig"))
        reader = csv.DictReader(decoded)
        created = updated = 0
        errors: list[str] = []

        for line, row in enumerate(reader, start=2):
            name = (row.get("display_name") or "").strip()
            if not name:
                errors.append(f"Row {line}: no display_name, skipped.")
                continue

            defaults = {
                key: (row.get(key) or "").strip()
                for key in (
                    "credentials",
                    "practice_name",
                    "city",
                    "region",
                    "postal_code",
                    "phone",
                    "email",
                    "website",
                )
            }
            defaults["tier"] = (row.get("tier") or "standard").strip() or "standard"
            defaults["offers_telehealth"] = _as_bool(row.get("offers_telehealth"))
            defaults["is_published"] = publish

            for field in ("latitude", "longitude"):
                value = (row.get(field) or "").strip()
                if value:
                    try:
                        defaults[field] = float(value)
                    except ValueError:
                        errors.append(f"Row {line}: {field} '{value}' is not a number.")

            practitioner, was_created = Practitioner.objects.update_or_create(
                display_name=name, defaults=defaults
            )
            created, updated = (
                (created + 1, updated) if was_created else (created, updated + 1)
            )

            _link_names(practitioner.modalities, Modality, row.get("modalities"))
            _link_names(practitioner.concerns, HealthConcern, row.get("concerns"))

            if geocode_missing and not practitioner.has_location:
                address = ", ".join(
                    p
                    for p in (
                        practitioner.city,
                        practitioner.region,
                        practitioner.postal_code,
                    )
                    if p
                )
                result = geocode(address) if address else None
                if result:
                    practitioner.latitude = result.latitude
                    practitioner.longitude = result.longitude
                    practitioner.save(update_fields=["latitude", "longitude"])

        return created, updated, errors


CSV_COLUMNS = [
    "display_name",
    "credentials",
    "practice_name",
    "city",
    "region",
    "postal_code",
    "phone",
    "email",
    "website",
    "modalities",
    "concerns",
    "tier",
    "offers_telehealth",
    "latitude",
    "longitude",
]


def _as_bool(value) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _link_names(relation, model, raw) -> None:
    """Attach pipe-separated names, creating any that do not exist yet."""
    names = [part.strip() for part in (raw or "").split("|") if part.strip()]
    if not names:
        return
    objects = [model.objects.get_or_create(name=name)[0] for name in names]
    relation.set(objects)


class RecommendationInline(admin.TabularInline):
    model = Recommendation
    extra = 0
    readonly_fields = ("practitioner", "rank", "score", "distance_miles", "reasons")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(RecommendationRequest)
class RecommendationRequestAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "location_label",
        "concern_list",
        "result_count",
        "email",
        "radius_miles",
    )
    list_filter = (
        "created_at",
        "result_count",
        "include_telehealth",
        "accepting_new_patients_only",
    )
    search_fields = ("location_label", "email", "user__email")
    date_hierarchy = "created_at"
    filter_horizontal = ("concerns", "modalities")
    inlines = (RecommendationInline,)
    readonly_fields = (
        "claim_token",
        "ip_hash",
        "user_agent",
        "result_count",
        "created_at",
        "updated_at",
    )

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("concerns")

    @admin.display(description="Looking for")
    def concern_list(self, obj):
        names = [c.name for c in obj.concerns.all()]
        return ", ".join(names) if names else "—"

    def has_add_permission(self, request):
        # These are records of what visitors did; creating one by hand would be
        # fabricating usage data.
        return False
