"""
Tenant schema URL configuration.
This file is served for every request to a tenant subdomain
(e.g. acme.api.inventory.com).
Public-schema requests (api.inventory.com) go to urls_public.py instead.
"""
from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse
from django.db import connection
from rest_framework import permissions
from rest_framework_simplejwt.views import TokenRefreshView
from drf_yasg.views import get_schema_view
from drf_yasg import openapi

from inventory_core import settings

schema_view = get_schema_view(
    openapi.Info(
        title='LogsInventory Tenant API',
        default_version='v1',
        description='Per-tenant API: authentication, POS and inventory.',
        contact=openapi.Contact(email='logscontactmail@gmail.com'),
        license=openapi.License(name='AEACBIO License'),
    ),
    public=True,
    permission_classes=[permissions.AllowAny],
    authentication_classes=[],
)


def health_check(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
        return JsonResponse(
            {'status': 'healthy', 'schema': connection.schema_name}, status=200
        )
    except Exception as e:
        return JsonResponse({'status': 'unhealthy', 'error': str(e)}, status=500)


urlpatterns = [
    path('admin/', admin.site.urls),
    path('health/', health_check, name='health_check'),

    # Swagger
    path('', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    path('api/api.json/', schema_view.without_ui(cache_timeout=0), name='schema-json'),
    path('redoc/', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),

    # Authentication — register, login, logout, verify, password reset, token refresh
    path('auth/', include('inventory_apps.authentication.urls')),

    # POS & Inventory — stores, roles, categories, products, invoices, reports, sync
    path('pos/', include('inventory_apps.pos_app.urls')),
]

if settings.DEBUG:
    from django.conf.urls.static import static
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
