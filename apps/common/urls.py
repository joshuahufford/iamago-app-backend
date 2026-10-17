from django.db import transaction
from django.urls import path

from apps.common.views import HealthView

# ATOMIC_REQUESTS opens a transaction before the view runs, which would raise
# an OperationalError (500) when the database is down — exactly the case the
# probe exists to report. Opting out lets the view answer with a 503 instead.
urlpatterns = [
    path(
        "health/",
        transaction.non_atomic_requests(HealthView.as_view()),
        name="health",
    ),
]
