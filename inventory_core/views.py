"""
Shared views — included in BOTH urls.py (tenant) and urls_public.py (public).
These views must work regardless of which PostgreSQL schema is currently active.
"""

from django.db import connection
from django.http import JsonResponse


def health_check(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return JsonResponse(
            {"status": "healthy", "schema": connection.schema_name}, status=200
        )
    except Exception as e:
        return JsonResponse({"status": "unhealthy", "error": str(e)}, status=500)
