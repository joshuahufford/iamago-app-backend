from django.urls import path

from apps.directory.views import (
    GeocodeView,
    HealthConcernListView,
    MapConfigView,
    ModalityListView,
    PractitionerDetailView,
    PractitionerEventView,
    RecommendationRequestCreateView,
    RecommendationRequestDetailView,
)

urlpatterns = [
    path("modalities/", ModalityListView.as_view(), name="modality-list"),
    path("concerns/", HealthConcernListView.as_view(), name="concern-list"),
    path(
        "practitioners/<uuid:pk>/",
        PractitionerDetailView.as_view(),
        name="practitioner-detail",
    ),
    path(
        "recommendations/",
        RecommendationRequestCreateView.as_view(),
        name="recommendation-create",
    ),
    path(
        "recommendations/<uuid:pk>/",
        RecommendationRequestDetailView.as_view(),
        name="recommendation-detail",
    ),
    path("events/", PractitionerEventView.as_view(), name="practitioner-event"),
    path("geocode/", GeocodeView.as_view(), name="geocode"),
    path("map-config/", MapConfigView.as_view(), name="map-config"),
]
