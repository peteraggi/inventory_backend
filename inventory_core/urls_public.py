"""
Public schema URL configuration.
Handles requests to the root domain (api.logsng.tech) — onboarding and plans.
Tenant-specific requests (acme.api.logsng.tech) use urls.py instead.
"""

from django.conf import settings
from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse, HttpResponse, HttpResponseForbidden
from django.db import connection
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi

from inventory_apps.clients.models import Domain

# Define API patterns first so swagger only documents these routes,
# not the tenant URL conf that get_schema_view would pick up by default.
_public_api_patterns = [
    path("platform/", include("inventory_apps.clients.urls")),
]

schema_view = get_schema_view(
    openapi.Info(
        title="LogsInventory Platform API",
        default_version="v1",
        description="Platform-level API: onboarding and subscription plans.",
        contact=openapi.Contact(email="logscontactmail@gmail.com"),
    ),
    public=True,
    permission_classes=[permissions.AllowAny],
    authentication_classes=[],
    patterns=_public_api_patterns,
)


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
    Caddy on_demand_tls "ask" callback — called before issuing a
    Let's Encrypt cert for a hostname it hasn't seen before. Only the
    base domain and subdomains with a provisioned tenant Domain are allowed,
    so a guessed/unowned subdomain can't burn ACME issuance quota.
    """
    domain = request.GET.get("domain", "").lower().strip()
    base_domain = settings.BASE_DOMAIN
    if domain == base_domain:
        return HttpResponse("ok")
    if domain.endswith(f".{base_domain}") and Domain.objects.filter(
        domain=domain
    ).exists():
        return HttpResponse("ok")
    return HttpResponseForbidden("domain not permitted")


urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health_check, name="health_check"),
    path("internal/tls-ask/", tls_ask, name="tls_ask"),
    # Swagger (public)
    path("", schema_view.with_ui("swagger", cache_timeout=0), name="schema-swagger-ui"),
    path("api/api.json/", schema_view.without_ui(cache_timeout=0), name="schema-json"),
    path("redoc/", schema_view.with_ui("redoc", cache_timeout=0), name="schema-redoc"),
    # Onboarding + plans
    path("platform/", include("inventory_apps.clients.urls")),
]
