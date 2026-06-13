"""
Public schema URL configuration.
Handles requests to the root domain (api.inventory.com) — onboarding and plans.
Tenant-specific requests (acme.api.inventory.com) use urls.py instead.
"""

from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse
from django.db import connection
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi

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
    # url='https://localhost:',
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


urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health_check, name="health_check"),
    # Swagger (public)
    path("", schema_view.with_ui("swagger", cache_timeout=0), name="schema-swagger-ui"),
    path("api/api.json/", schema_view.without_ui(cache_timeout=0), name="schema-json"),
    path("redoc/", schema_view.with_ui("redoc", cache_timeout=0), name="schema-redoc"),
    # Onboarding + plans
    path("platform/", include("inventory_apps.clients.urls")),
]
