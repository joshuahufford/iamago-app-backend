import uuid

from django.db import models


class TimeStampedModel(models.Model):
    """Abstract base with a UUID primary key and created/updated timestamps.

    Domain models should inherit from this so every table gets non-guessable
    ids and a consistent audit trail for free.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ("-created_at",)
