"""Notifications for outreach."""

from apps.common.mail import send_templated_email, site_url
from apps.outreach.models import ContactRequest


def notify_contact_request(contact: ContactRequest) -> dict[str, bool]:
    """Tell the practitioner, and confirm to the patient.

    Both are best-effort. A mail outage must not lose the request itself — the
    row is already saved, and the portal shows it regardless.
    """
    practitioner = contact.practitioner
    concerns = ", ".join(concern.name for concern in contact.shared_concerns)
    location = (
        contact.recommendation_request.location_label
        if contact.recommendation_request_id
        else ""
    )

    recommendation_url = ""
    if contact.recommendation_request_id:
        source = contact.recommendation_request
        recommendation_url = (
            f"{site_url()}/recommendations/{source.id}?token={source.claim_token}"
        )

    to_practitioner = send_templated_email(
        "contact_request_practitioner",
        to=practitioner.email,
        context={
            "contact": contact,
            "practitioner": practitioner,
            "concerns": concerns,
            "location": location,
        },
        # Replying should reach the patient, not a no-reply mailbox.
        reply_to=[contact.email],
    )

    to_patient = send_templated_email(
        "contact_request_patient",
        to=contact.email,
        context={
            "contact": contact,
            "practitioner": practitioner,
            "recommendation_url": recommendation_url,
        },
    )

    return {"practitioner": to_practitioner, "patient": to_patient}


def email_recommendations(recommendation_request, to: str) -> bool:
    """Send a visitor their matches, so they can come back to them later."""
    recommendations = list(
        recommendation_request.recommendations.select_related("practitioner")
    )
    return send_templated_email(
        "recommendations_ready",
        to=to,
        context={
            "recommendations": recommendations,
            "count": len(recommendations),
            "request_location": recommendation_request.location_label,
            "recommendation_url": (
                f"{site_url()}/recommendations/{recommendation_request.id}"
                f"?token={recommendation_request.claim_token}"
            ),
        },
    )
