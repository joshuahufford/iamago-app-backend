from django.urls import path

from apps.outreach.views import ContactRequestCreateView, EmailRecommendationsView

urlpatterns = [
    path(
        "contact-requests/",
        ContactRequestCreateView.as_view(),
        name="contact-request-create",
    ),
    path(
        "recommendations/<uuid:pk>/email/",
        EmailRecommendationsView.as_view(),
        name="recommendations-email",
    ),
]
