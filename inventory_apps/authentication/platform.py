# inventory_apps/authentication/platform.py
"""
Platform sign-in on the root domain: find the businesses an account belongs to, then sign
in to one of them. Served from the public schema, so the user is found before any business
is chosen. Nothing about a business is revealed until the password is correct.
"""
import logging

from django.contrib import auth
from django.core import signing
from django_tenants.utils import schema_context
from rest_framework import permissions, status
from rest_framework.exceptions import APIException, PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from rest_framework_simplejwt.authentication import JWTAuthentication

from inventory_apps.authentication.models import User
from inventory_apps.authentication.ratelimit import client_ip, enforce
from inventory_apps.clients.models import WorkspaceMembership
from inventory_apps.clients.workspaces import workspace_slug

logger = logging.getLogger(__name__)


class SignInFailed(APIException):
    """Bad credentials or an expired selection. 401, and the same message whichever check failed."""
    status_code = 401
    default_detail = "Invalid credentials"
    default_code = "sign_in_failed"

SELECTION_SALT = "platform-workspace-selection"
SELECTION_MAX_AGE = 300  # seconds


def _signer():
    return signing.TimestampSigner(salt=SELECTION_SALT)


def _authenticated_user(email, password):
    user = User.objects.filter(email=(email or "").lower().strip()).first()
    if user is None or not password:
        raise SignInFailed("Invalid credentials")
    user = auth.authenticate(email=user.email, password=password)
    if user is None:
        raise SignInFailed("Invalid credentials, try again")
    if not user.is_active:
        raise SignInFailed("Account disabled, contact admin")
    if not user.is_verified:
        raise SignInFailed("Email is not verified")
    return user


def _business_details(membership):
    """Business name, the user's role and store there. Read inside that business's schema."""
    client = membership.client
    with schema_context(client.schema_name):
        from inventory_apps.pos_app.models import Role, Store
        role = Role.objects.filter(pk=membership.role_id).first() if membership.role_id else None
        store = Store.objects.filter(pk=membership.store_id).first() if membership.store_id else None
    return {
        "subdomain": workspace_slug(client),
        "business_name": client.name,
        "role": role.name if role else "",
        "role_display": role.display_name if role else "",
        "store_name": store.name if store else "",
    }


def _workspaces_for(user):
    """Every business the user belongs to that is open to use, with its selection token."""
    from inventory_apps.clients.approval import closed_reason

    memberships = list(
        WorkspaceMembership.objects.filter(user=user, is_active=True)
        .select_related("client")
        .order_by("client__name")
    )
    open_memberships = [m for m in memberships if closed_reason(m.client) is None]
    if not open_memberships:
        if memberships:
            # Only businesses that are awaiting approval or deactivated: say which, so the user knows why.
            raise PermissionDenied(closed_reason(memberships[0].client))
        raise PermissionDenied("No business is linked to this account yet. Ask the business owner to invite you.")
    workspaces = [_business_details(m) for m in open_memberships]
    return {
        "selection_token": _signer().sign_object({"uid": str(user.pk)}),
        "workspaces": workspaces,
    }


class PlatformLoginView(APIView):
    """Email and password in, the list of businesses out, plus a short-lived selection token."""
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = (request.data.get("email") or "").lower().strip()
        enforce(f"signin:ip:{client_ip(request)}", limit=60, window_seconds=900)
        enforce(f"signin:email:{email}", limit=10, window_seconds=900)
        user = _authenticated_user(email, request.data.get("password"))
        return Response(_workspaces_for(user), status=status.HTTP_200_OK)


class PlatformSwitchView(APIView):
    """
    For a user already signed in: the businesses they belong to and a selection token, so they
    can move to another business without typing their password again.
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        return Response(_workspaces_for(request.user), status=status.HTTP_200_OK)


class PlatformSelectWorkspaceView(APIView):
    """Exchange the selection token and a chosen business for session tokens for that business."""
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        try:
            payload = _signer().unsign_object(request.data.get("selection_token", ""), max_age=SELECTION_MAX_AGE)
        except signing.BadSignature:
            raise SignInFailed("Your sign-in expired. Please sign in again.")

        user = User.objects.filter(pk=payload.get("uid")).first()
        if user is None or not user.is_active or not user.is_verified:
            raise SignInFailed("Your sign-in expired. Please sign in again.")

        subdomain = (request.data.get("subdomain") or "").strip().lower()
        membership = next(
            (
                m for m in WorkspaceMembership.objects.filter(user=user, is_active=True).select_related("client")
                if workspace_slug(m.client) == subdomain
            ),
            None,
        )
        if membership is None:
            raise PermissionDenied("You are not a member of that business.")
        from inventory_apps.clients.approval import closed_reason
        reason = closed_reason(membership.client)
        if reason:
            raise PermissionDenied(reason)

        details = _business_details(membership)
        return Response({
            "email": user.email,
            "name": user.name,
            "username": user.username,
            "user_id": str(user.pk),
            "store_id": str(membership.store_id or ""),
            "store_name": details["store_name"],
            "role": details["role"],
            "subdomain": details["subdomain"],
            "tenant": {
                "id": str(membership.client.pk),
                "business_name": membership.client.name,
                "subdomain": details["subdomain"],
            },
            "tokens": user.tokens(),
        }, status=status.HTTP_200_OK)
