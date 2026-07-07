"""
Shared views — included in BOTH urls.py (tenant) and urls_public.py (public).
These views must work regardless of which PostgreSQL schema is currently active.
"""

from django.conf import settings
from django.db import connection
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse

from inventory_apps.clients.models import Domain


def health_check(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return JsonResponse(
            {"status": "healthy", "schema": connection.schema_name}, status=200
        )
    except Exception as e:
        return JsonResponse({"status": "unhealthy", "error": str(e)}, status=500)


def tls_ask(request):
    """
    Caddy on_demand_tls "ask" callback.
    Called before Caddy issues a TLS cert for an unknown hostname.
    Must be reachable from both URL confs because the Host header on the
    internal callback request is the backend container name, not a known domain,
    so TenantMainMiddleware may activate either conf.
    """
    domain = request.GET.get("domain", "").lower().strip()
    base_domain = settings.BASE_DOMAIN  # e.g. api.logsng.tech

    # Always allow the root API domain itself
    if domain == base_domain:
        return HttpResponse("ok")

    # Allow any subdomain that has a provisioned tenant Domain row
    if domain.endswith(f".{base_domain}") and Domain.objects.filter(domain=domain).exists():
        return HttpResponse("ok")

    return HttpResponseForbidden("domain not permitted")
