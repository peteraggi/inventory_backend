"""
Shared views — included in BOTH urls.py (tenant) and urls_public.py (public).
These views must work regardless of which PostgreSQL schema is currently active.
"""

import logging

from django.db import connection
from django.http import JsonResponse

logger = logging.getLogger(__name__)


def health_check(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return JsonResponse(
            {"status": "healthy", "schema": connection.schema_name}, status=200
        )
    except Exception:
        logger.exception("Health check failed")
        return JsonResponse({"status": "unhealthy"}, status=500)
