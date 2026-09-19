from rest_framework.permissions import BasePermission


class IsClaimedPractitioner(BasePermission):
    """Only a signed-in user whose account is linked to a listing.

    The link is the authorisation: everything in the portal is scoped to
    ``request.user.practitioner``, so a user with no listing has nothing to see
    and a user with one can only ever see their own.
    """

    message = "This account is not linked to a practitioner listing."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and getattr(request.user, "practitioner", None) is not None
        )
