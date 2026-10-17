from django.urls import path

from apps.portal.views import (
    PortalContactRequestDetailView,
    PortalContactRequestListView,
    PortalPractitionerView,
    PortalStatsView,
)

urlpatterns = [
    path("me/", PortalPractitionerView.as_view(), name="portal-me"),
    path("stats/", PortalStatsView.as_view(), name="portal-stats"),
    path(
        "contact-requests/",
        PortalContactRequestListView.as_view(),
        name="portal-contact-requests",
    ),
    path(
        "contact-requests/<uuid:pk>/",
        PortalContactRequestDetailView.as_view(),
        name="portal-contact-request-detail",
    ),
]
