# inventory_core/exceptions.py

"""
Project-wide API error envelope: every ERP module returns {success, error, details}.
Views opt in with a mixin whose get_exception_handler() returns inventory_exception_handler.
"""

from rest_framework.views import exception_handler


def _first_message(data):
    """Return the first human-readable message found in a DRF error payload."""
    if isinstance(data, dict):
        for value in data.values():
            message = _first_message(value)
            if message:
                return message
        return ""
    if isinstance(data, (list, tuple)):
        for value in data:
            message = _first_message(value)
            if message:
                return message
        return ""
    return str(data)


def _field_message(data):
    """Like _first_message, but prefixes the field name so the toast says which input failed."""
    if not isinstance(data, dict):
        return _first_message(data)
    for key, value in data.items():
        message = _first_message(value)
        if message:
            return message if key in ("error", "non_field_errors") else f"{key}: {message}"
    return ""


def inventory_exception_handler(exc, context):
    """
    Normalise every inventory error into {"success": False, "error": "...", "details": ...}.

    The frontend reads `response.data.error` for toasts; DRF's default shapes
    ({"detail": ...} or {"field": [...]}) would otherwise fall back to generic text.
    """
    response = exception_handler(exc, context)
    if response is None:
        return None

    data = response.data
    if isinstance(data, dict) and "detail" in data:
        message = str(data["detail"])
        details = None
    else:
        message = _field_message(data) or "Request failed."
        details = data if isinstance(data, dict) else None

    response.data = {"success": False, "error": message, "details": details}
    return response
