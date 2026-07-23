# authentication/permissions.py

from rest_framework import permissions


class IsOwnerOrManager(permissions.BasePermission):
    """
    Permission to only allow store owners and managers to access certain views.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        return bool(request.user.role) and request.user.role.name in ["owner", "manager"]
