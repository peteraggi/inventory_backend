"""
Public schema URL configuration.
Handles requests to the root domain (api.logsng.tech) — onboarding and plans.
Tenant-specific requests (acme.api.logsng.tech) use urls.py instead.
"""

from django.contrib import admin
from django.urls import path, include
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi

from inventory_core.views import health_check

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


urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health_check, name="health_check"),
    path("internal/", include("inventory_apps.infrastructure.caddy.urls")),
    # Swagger (public)
    path("", schema_view.with_ui("swagger", cache_timeout=0), name="schema-swagger-ui"),
    path("api/api.json/", schema_view.without_ui(cache_timeout=0), name="schema-json"),
    path("redoc/", schema_view.with_ui("redoc", cache_timeout=0), name="schema-redoc"),
    # Onboarding + plans
    path("platform/", include("inventory_apps.clients.urls")),
]
