from django.contrib import admin
from django.utils.html import format_html

from apps.outreach.models import ContactRequest, ContactRequestAccess


class ContactRequestAccessInline(admin.TabularInline):
    """The audit trail for this request. Read-only, by design."""

    model = ContactRequestAccess
    extra = 0
    readonly_fields = ("actor", "ip_hash", "created_at")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ContactRequest)
class ContactRequestAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "name",
        "practitioner",
        "tier_of",
        "status",
        "shared",
        "first_viewed_at",
    )
    list_filter = ("status", "share_concerns", "created_at", "practitioner__tier")
    search_fields = ("name", "email", "phone", "practitioner__display_name")
    date_hierarchy = "created_at"
    autocomplete_fields = ("practitioner",)
    inlines = (ContactRequestAccessInline,)
    readonly_fields = (
        "consent_text",
        "consented_at",
        "ip_hash",
        "first_viewed_at",
        "responded_at",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        ("Patient", {"fields": ("name", "email", "phone", "message")}),
        (
            "Practitioner",
            {"fields": ("practitioner", "recommendation_request", "patient")},
        ),
        (
            "Consent",
            {
                "fields": ("share_concerns", "consent_text", "consented_at", "ip_hash"),
                "description": (
                    "The wording stored here is what the patient actually agreed "
                    "to at the time. It is never rewritten when the current "
                    "consent copy changes."
                ),
            },
        ),
        (
            "Handling",
            {
                "fields": (
                    "status",
                    "practitioner_note",
                    "first_viewed_at",
                    "responded_at",
                )
            },
        ),
    )

    def has_add_permission(self, request):
        # These are records of what a patient asked for; creating one by hand
        # would be fabricating consent.
        return False

    @admin.display(description="Tier", ordering="practitioner__tier")
    def tier_of(self, obj):
        return obj.practitioner.get_tier_display()

    @admin.display(description="Shared concerns", boolean=True)
    def shared(self, obj):
        return obj.share_concerns


@admin.register(ContactRequestAccess)
class ContactRequestAccessAdmin(admin.ModelAdmin):
    """Who opened which enquiry, and when."""

    list_display = ("created_at", "actor", "contact_request", "visitor")
    list_filter = ("created_at",)
    search_fields = ("actor__email", "contact_request__name")
    date_hierarchy = "created_at"

    @admin.display(description="From (hashed)")
    def visitor(self, obj):
        return format_html("<code>{}…</code>", obj.ip_hash[:16]) if obj.ip_hash else "—"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        # An audit trail you can delete from the admin is not an audit trail.
        return False
