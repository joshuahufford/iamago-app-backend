from django.urls import path

from apps.patients.views import ClaimSearchView, SavedEnquiryListView, SavedSearchListView

urlpatterns = [
    path("searches/", SavedSearchListView.as_view(), name="patient-searches"),
    path("searches/claim/", ClaimSearchView.as_view(), name="patient-claim-search"),
    path("enquiries/", SavedEnquiryListView.as_view(), name="patient-enquiries"),
]
