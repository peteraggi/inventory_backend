# inventory_apps/clients/workspaces.py
"""
Business (workspace) membership helpers.

A user's store and role are looked up in the schema of the business they are working in,
so the same person can hold different roles in different businesses. These helpers record
those links and find the right one for a request.
"""
from django.db import connection

from inventory_apps.clients.models import WorkspaceMembership


def current_client():
    """The business the current request is served for, or None on the public schema."""
    client = getattr(connection, "tenant", None)
    if client is None or client.schema_name == "public":
        return None
    return client


def workspace_slug(client):
    """The subdomain a business is reached through, e.g. 'acme' for acme.api.logsng.tech."""
    domain = client.domains.filter(is_primary=True).first() or client.domains.first()
    return domain.domain.split(".")[0] if domain else client.schema_name


def link_user(user, store_id=None, role_id=None, client=None, permission_overrides=None):
    """Record (or update) that `user` belongs to `client` with the given store and role."""
    client = client or current_client()
    if client is None:
        return None
    membership, _ = WorkspaceMembership.objects.update_or_create(
        user=user,
        client=client,
        defaults={
            "store_id": store_id,
            "role_id": role_id,
            "is_active": True,
            **({"permission_overrides": permission_overrides} if permission_overrides is not None else {}),
        },
    )
    return membership


def membership_for_current(user):
    """The user's membership in the current business, creating it from their stored store and role if missing."""
    client = current_client()
    if client is None:
        return None
    membership = WorkspaceMembership.objects.filter(user=user, client=client).first()
    if membership is None:
        membership = link_user(
            user,
            store_id=user.store_id,
            role_id=user.role_id,
            client=client,
            permission_overrides=user.permission_overrides or {},
        )
    return membership


def active_memberships(user):
    return WorkspaceMembership.objects.filter(user=user, is_active=True).select_related("client")
