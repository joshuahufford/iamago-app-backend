"""Sending transactional mail.

Every message is rendered from a template pair — ``<name>.subject.txt`` and
``<name>.body.txt`` — so the copy lives with the other templates rather than
buried in view code, and the subject can never drift from the body.

Sending is best-effort by default: a mail outage must not fail the request that
triggered it, because losing a contact request is far worse than losing its
notification. Failures are logged and reported by the return value.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def site_url() -> str:
    return getattr(settings, "SITE_URL", "http://localhost:5173").rstrip("/")


def send_templated_email(
    template: str,
    *,
    to: list[str] | str,
    context: dict | None = None,
    reply_to: list[str] | None = None,
    fail_silently: bool = True,
) -> bool:
    """Render ``templates/email/<template>.*`` and send it.

    Returns whether the message was handed to the backend.
    """
    recipients = [to] if isinstance(to, str) else list(to)
    recipients = [address for address in recipients if address]
    if not recipients:
        return False

    context = {"site_url": site_url(), **(context or {})}

    subject = render_to_string(f"email/{template}.subject.txt", context).strip()
    body = render_to_string(f"email/{template}.body.txt", context)

    message = EmailMultiAlternatives(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=recipients,
        reply_to=reply_to or None,
    )

    try:
        message.send(fail_silently=False)
    except Exception:
        logger.exception("Could not send %r to %s", template, recipients)
        if not fail_silently:
            raise
        return False

    return True
