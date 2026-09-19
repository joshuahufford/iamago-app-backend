from django.urls import path

from apps.common.views import HealthView

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
]
