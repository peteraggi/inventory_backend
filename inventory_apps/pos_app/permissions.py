# pos_app/permissions.py

from rest_framework import permissions


class IsOwner(permissions.BasePermission):
    """
    Permission to only allow store owners to access certain views.
    """

    def has_permission(self, request, view):
        """Check if user is authenticated and is a store owner"""
        if not request.user or not request.user.is_authenticated:
            return False

        return request.user.role.name == "owner"


class IsOwnerOrReadOnly(permissions.BasePermission):
    """
    Permission to allow owners full access, others read-only.
    """

    def has_permission(self, request, view):
        """Check if user is authenticated"""
        if not request.user or not request.user.is_authenticated:
            return False

        # Read permissions for any authenticated user
        if request.method in permissions.SAFE_METHODS:
            return True

        # Write permissions only for owners
        return request.user.role.name == "owner"


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


class IsSalespersonOrOwner(permissions.BasePermission):
    """
    Permission to allow salesperson to access their own resources and owners to access all.
    """

    def has_permission(self, request, view):
        """Check if user is authenticated"""
        if not request.user or not request.user.is_authenticated:
            return False

        return request.user.role.name in ["salesperson", "owner", "manager"]

    def has_object_permission(self, request, view, obj):
        """Check if user can access this specific object"""
        if not request.user or not request.user.is_authenticated:
            return False

        # Owners and managers can access everything in their store
        if request.user.role.name in ["owner", "manager"]:
            if hasattr(obj, "store"):
                return obj.store == request.user.store
            return True

        # Salespeople can only access their own resources
        if request.user.role.name == "salesperson":
            # Check if object has a salesperson or user attribute
            if hasattr(obj, "salesperson"):
                return obj.salesperson == request.user
            if hasattr(obj, "user"):
                return obj.user == request.user

        return False


class CanCreateInvoice(permissions.BasePermission):
    """
    Permission to allow only authenticated users from active stores to create invoices.
    """

    def has_permission(self, request, view):
        """Check if user can create invoices"""
        if not request.user or not request.user.is_authenticated:
            return False

        # Check if user's store is active
        if not request.user.store or not request.user.store.is_active:
            return False

        # Check if user has appropriate role
        return request.user.role.name in ["salesperson", "owner", "manager"]


class CanViewReports(permissions.BasePermission):
    """
    Permission to allow only owners and managers to view reports.
    """

    def has_permission(self, request, view):
        """Check if user can view reports"""
        if not request.user or not request.user.is_authenticated:
            return False

        return request.user.role.name in ["owner", "manager"]
