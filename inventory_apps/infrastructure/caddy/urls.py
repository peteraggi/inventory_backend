"""
URL patterns for Caddy infrastructure callbacks.

Registered under the ``internal/`` prefix in BOTH URL confs:

    # urls.py (tenant schema)
    # urls_public.py (public schema)
    path("internal/", include("inventory_apps.infrastructure.caddy.urls")),

The endpoint must live in both confs because Caddy's on_demand_tls ``ask``
callback carries ``Host: inventory_backend_app:8400`` (the Docker service name),
which django-tenants does not recognise as a tenant domain.  Depending on
``SHOW_PUBLIC_IF_NO_TENANT_FOUND``, Django may activate either URL conf for
this internal request.  Registering the endpoint in both confs guarantees it is
always reachable regardless of which conf is selected.
"""

from django.urls import path

from . import views

app_name = "caddy"

urlpatterns = [
    path("tls-ask/", views.tls_ask, name="tls_ask"),
]
