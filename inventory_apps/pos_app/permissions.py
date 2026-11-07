# pos_app/permissions.py
"""
Permissions for the legacy POS endpoints, checked against the same role matrix as the ERP
modules. A view declares `legacy_resource` (e.g. "sales", "reports", "settings") and the
request method decides the action: GET reads, POST creates, PUT/PATCH update, DELETE deletes.
A view that confirms, validates or posts a document sets `legacy_action = "update"` instead.
"""
from rest_framework import permissions

from inventory_apps.authentication.permissions import METHOD_ACTIONS
from inventory_apps.authentication.rbac import user_can


class HasLegacyResource(permissions.BasePermission):
    """Matrix check for legacy views, refused for stores that are switched off."""

    def has_permission(self, request, view):
        resource = getattr(view, "legacy_resource", None)
        user = request.user
        if not resource or not user or not user.is_authenticated:
            return False
        if user.store and not user.store.is_active:
            return False
        action = getattr(view, "legacy_action", None) or METHOD_ACTIONS.get(request.method, "update")
        return user_can(user, resource, action)


class IsSameStore(permissions.BasePermission):
    """
    Permission to ensure users can only access resources from their own store.
    """

    def has_object_permission(self, request, view, obj):
        """Check if the object belongs to user's store"""
        if not request.user or not request.user.is_authenticated:
            return False

        # Check if object has a store attribute
        if hasattr(obj, "store"):
            return obj.store == request.user.store

        # If no store attribute, deny by default
        return False
