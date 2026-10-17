from rest_framework.views import exception_handler as drf_exception_handler


def exception_handler(exc, context):
    """Wrap DRF errors in a consistent ``{"detail", "errors"}`` envelope.

    The frontend reads ``errors`` for field-level messages and falls back to
    ``detail`` for everything else, so every failure looks the same there.
    """
    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    data = response.data
    if isinstance(data, dict) and "detail" in data and len(data) == 1:
        payload = {"detail": str(data["detail"]), "errors": {}}
    elif isinstance(data, dict):
        payload = {"detail": "Validation failed.", "errors": data}
    else:
        payload = {"detail": "Request failed.", "errors": {"non_field_errors": data}}

    response.data = payload
    return response
