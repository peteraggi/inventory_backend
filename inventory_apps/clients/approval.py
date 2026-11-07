# inventory_apps/clients/approval.py
"""
Super admin decisions on businesses. A business can be used only when it is approved and
active. The gate is checked on every request, so deactivating a business takes effect
straight away, even for people who are already signed in.
"""
from django.utils import timezone


def closed_reason(client):
    """Why nobody can use this business right now, or None when it is open."""
    if client.approval_status != "approved":
        return "This business is awaiting approval from the platform team."
    if not client.is_active:
        return "This business has been deactivated. Contact the platform team."
    return None


def approve(client, by_email=""):
    client.approval_status = "approved"
    client.approved_at = timezone.now()
    client.approved_by = by_email or ""
    client.save(update_fields=["approval_status", "approved_at", "approved_by", "updated_at"])


def set_active(client, active):
    client.is_active = active
    client.save(update_fields=["is_active", "updated_at"])
