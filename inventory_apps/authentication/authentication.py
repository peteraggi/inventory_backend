# inventory_apps/authentication/authentication.py
"""
JWT authentication that places the user in the business they are working in.

A user's store, role and individual grants come from their membership of the current
business (see clients/workspaces.py). For the request they are set on the user object; they
are never saved back. Users who have no memberships yet keep the values stored on their row.
"""
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication


class WorkspaceJWTAuthentication(JWTAuthentication):

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        user, token = result
        refuse_if_business_closed()
        apply_workspace(user)
        return user, token


def refuse_if_business_closed():
    """A business that is awaiting approval or deactivated cannot be used, even with a valid token."""
    from inventory_apps.clients.approval import closed_reason
    from inventory_apps.clients.workspaces import current_client

    client = current_client()
    reason = closed_reason(client) if client else None
    if reason:
        raise PermissionDenied(reason)


def apply_workspace(user):
    from inventory_apps.clients.workspaces import current_client
    from inventory_apps.pos_app.models import Role, Store

    from inventory_apps.clients.models import WorkspaceMembership

    if not WorkspaceMembership.objects.filter(user=user).exists():
        return  # not yet linked to any business: keep the values on the user row

    client = current_client()
    membership = WorkspaceMembership.objects.filter(user=user, client=client).first() if client else None
    if membership is None or not membership.is_active:
        if user.is_superuser:
            return
        raise AuthenticationFailed("This account is not linked to this business.")

    user.store = Store.objects.filter(pk=membership.store_id).first()
    user.role = Role.objects.filter(pk=membership.role_id).first()
    user.permission_overrides = membership.permission_overrides or {}
    user.current_membership = membership
