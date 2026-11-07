# inventory_apps/authentication/ratelimit.py
"""
Fixed-window attempt limits for sign-in and password reset, kept in the shared cache.

If the cache cannot be reached the request is allowed and the failure is logged, so a cache
outage does not lock every user out. Limits resume when the cache is back.
"""
import logging

from django.core.cache import cache
from rest_framework.exceptions import APIException
from rest_framework import status

logger = logging.getLogger(__name__)


class TooManyAttempts(APIException):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_detail = "Too many attempts. Please wait a few minutes and try again."
    default_code = "too_many_attempts"


def allow(key, limit, window_seconds):
    """Record one attempt under `key`. Returns False once `limit` attempts fall in the window."""
    try:
        try:
            count = cache.incr(key)
        except ValueError:
            cache.add(key, 1, timeout=window_seconds)
            count = 1
    except Exception:  # cache unavailable: fail open, but say so
        logger.warning("rate limit cache unavailable for %s", key, exc_info=True)
        return True
    return count <= limit


def enforce(key, limit, window_seconds):
    if not allow(key, limit, window_seconds):
        raise TooManyAttempts()


def client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR", "unknown")
