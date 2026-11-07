# authentication/permissions.py

from rest_framework import permissions





METHOD_ACTIONS = {
    "GET": "read",
    "HEAD": "read",
    "OPTIONS": "read",
    "POST": "create",
    "PUT": "update",
    "PATCH": "update",
    "DELETE": "delete",
}


class HasErpPermission(permissions.BasePermission):
    """
    Checks the user's role matrix plus individual grants for the view's resource.

    A view declares:
      erp_resource      - the module, e.g. "inventory" (required; fails closed without it)
      erp_action_map    - optional {viewset action name: "read"|"create"|"update"|"delete"}
                          for custom actions such as validate/confirm, which change stock
                          and so count as "update". Unlisted actions use the HTTP method.
    """

    def has_permission(self, request, view):
        from inventory_apps.authentication.rbac import user_can

        resource = getattr(view, "erp_resource", None)
        if not resource:
            return False
        action_map = getattr(view, "erp_action_map", {})
        action = action_map.get(getattr(view, "action", None)) or METHOD_ACTIONS.get(request.method, "update")
        return user_can(request.user, resource, action)


class HasErpPermissionOrReadOnly(HasErpPermission):
    """Any signed-in user may read; writes need the view's resource permission."""

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS and request.user and request.user.is_authenticated:
            return True
        return super().has_permission(request, view)
