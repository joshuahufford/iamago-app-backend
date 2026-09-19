"""Visitor identification and the search rate limit.

Raw IP addresses are never stored. They are salted and hashed on the way in,
which is enough to count searches per visitor without holding an identifier we
would then have to protect.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date

from django.conf import settings
from django.db import models, transaction

from apps.analytics.models import SearchQuota


def client_ip(request) -> str:
    """Best-effort client address.

    ``X-Forwarded-For`` is only trusted when the deployment says how many
    proxies sit in front of the app, because the header is client-supplied and
    trivially spoofed otherwise. With ``TRUSTED_PROXY_COUNT = 1`` we take the
    last-but-one entry, which is the address our own proxy observed.
    """
    proxies = getattr(settings, "TRUSTED_PROXY_COUNT", 0)
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")

    if proxies and forwarded:
        parts = [part.strip() for part in forwarded.split(",") if part.strip()]
        if len(parts) >= proxies:
            return parts[-proxies]

    return request.META.get("REMOTE_ADDR", "") or "unknown"


def hash_ip(ip: str) -> str:
    salt = getattr(settings, "IP_HASH_SALT", "") or settings.SECRET_KEY
    return hashlib.sha256(f"{salt}:{ip}".encode()).hexdigest()


def visitor_hash(request) -> str:
    return hash_ip(client_ip(request))


@dataclass
class QuotaVerdict:
    allowed: bool
    # "email_required" once the anonymous allowance is spent, "rate_limited"
    # once even the email-backed allowance is spent.
    code: str = ""
    used: int = 0
    limit: int = 0

    @property
    def remaining(self) -> int:
        return max(self.limit - self.used, 0)


def anonymous_limit() -> int:
    return getattr(settings, "ANON_SEARCH_LIMIT_PER_DAY", 5)


def identified_limit() -> int:
    return getattr(settings, "EMAIL_SEARCH_LIMIT_PER_DAY", 25)


def check_quota(request, *, email: str = "", day: date | None = None) -> QuotaVerdict:
    """Consume one search from this visitor's daily allowance.

    Giving an email raises the ceiling rather than removing it — an email is a
    speed bump for a scraper, not a licence to take the whole directory.
    """
    ip_hash = visitor_hash(request)
    day = day or date.today()
    limit = identified_limit() if email else anonymous_limit()

    with transaction.atomic():
        quota, _ = SearchQuota.objects.get_or_create(ip_hash=ip_hash, day=day)
        # Re-read under a row lock so two concurrent searches cannot both pass
        # the check on the last remaining slot.
        quota = SearchQuota.objects.select_for_update().get(pk=quota.pk)

        if quota.search_count >= limit:
            code = "rate_limited" if email else "email_required"
            return QuotaVerdict(
                allowed=False, code=code, used=quota.search_count, limit=limit
            )

        quota.search_count += 1
        if email:
            quota.gave_email = True
        quota.save(update_fields=["search_count", "gave_email", "updated_at"])

    return QuotaVerdict(allowed=True, used=quota.search_count, limit=limit)


def record_block(request, *, day: date | None = None) -> None:
    """Count a refused search, so the dashboard shows the limit working."""
    SearchQuota.objects.filter(
        ip_hash=visitor_hash(request), day=day or date.today()
    ).update(blocked_count=models.F("blocked_count") + 1)
