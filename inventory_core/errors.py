# inventory_core/errors.py
"""
Turns an exception into a message that is safe to show a user.

Only messages written for people pass through: our own typed errors (DRF exceptions), Django
and DRF validation messages, and deliberate ValueErrors raised by services. Anything else,
including database and library text, is replaced by the fallback. The full exception should be
logged by the caller.
"""
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import APIException


def _flatten(value):
    """The first readable message from a nested DRF or Django error structure."""
    if isinstance(value, (list, tuple)):
        for item in value:
            found = _flatten(item)
            if found:
                return found
        return None
    if isinstance(value, dict):
        for item in value.values():
            found = _flatten(item)
            if found:
                return found
        return None
    text = str(value).strip()
    return text or None


def user_message(exc, fallback):
    """A message for the user about `exc`, or `fallback` when the exception has nothing safe to say."""
    if isinstance(exc, APIException):
        return _flatten(exc.detail) or fallback
    if isinstance(exc, DjangoValidationError):
        if hasattr(exc, "message_dict"):
            return _flatten(exc.message_dict) or fallback
        return _flatten(exc.messages) or fallback
    if isinstance(exc, ValueError):
        return str(exc) or fallback
    return fallback
