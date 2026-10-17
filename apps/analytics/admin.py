from django.contrib import admin
from django.utils.html import format_html

from apps.analytics.models import DailyStat, PractitionerEvent, SearchQuota


@admin.register(DailyStat)
class DailyStatAdmin(admin.ModelAdmin):
    """The usage dashboard.

    Rows are produced by ``manage.py rollup_usage``; nothing here is editable,
    because editing a rollup would just be lying to yourself.
    """

    list_display = (
        "day",
        "searches",
        "unique_visitors",
        "coverage_gap",
        "recommendations_served",
        "practitioner_impressions",
        "practitioner_clicks",
        "click_rate",
        "emails_captured",
        "blocked_requests",
    )
    list_filter = ("day",)
    date_hierarchy = "day"
    ordering = ("-day",)

    @admin.display(description="Found nobody", ordering="zero_result_searches")
    def coverage_gap(self, obj):
        """Zero-result searches: where you need to recruit."""
        if not obj.searches:
            return "—"
        share = obj.zero_result_searches / obj.searches
        color = "#b91c1c" if share > 0.2 else "#6b7280"
        # format_html escapes its arguments into SafeString, which has no
        # __format__ support for a spec like {:.0%} — so format the number
        # first and interpolate a plain string.
        return format_html(
            '<span style="color:{}">{} ({})</span>',
            color,
            obj.zero_result_searches,
            f"{share:.0%}",
        )

    @admin.display(description="Click rate")
    def click_rate(self, obj):
        return f"{obj.click_through_rate:.1%}" if obj.practitioner_impressions else "—"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(PractitionerEvent)
class PractitionerEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "practitioner", "kind", "tier_at_event")
    list_filter = ("kind", "tier_at_event", "created_at")
    search_fields = ("practitioner__display_name",)
    date_hierarchy = "created_at"
    autocomplete_fields = ("practitioner",)
    readonly_fields = ("created_at", "updated_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(SearchQuota)
class SearchQuotaAdmin(admin.ModelAdmin):
    """Per-visitor daily counters, for spotting abuse.

    Visitors appear as salted hashes — the raw addresses are never stored, so
    this shows you the shape of the traffic without holding identities.
    """

    list_display = ("day", "visitor", "search_count", "blocked_count", "gave_email")
    list_filter = ("day", "gave_email")
    date_hierarchy = "day"
    ordering = ("-day", "-search_count")
    search_fields = ("ip_hash",)

    @admin.display(description="Visitor (hashed)")
    def visitor(self, obj):
        return format_html("<code>{}…</code>", obj.ip_hash[:16])

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
