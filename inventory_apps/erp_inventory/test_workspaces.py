# inventory_apps/erp_inventory/test_workspaces.py
"""
Email sign-in that finds the user's businesses, business selection, and the per-business
store and role applied to each request.
"""
from django.core import signing
from unittest import mock

from django.core.cache.backends.locmem import LocMemCache
from django.test import RequestFactory
from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework_simplejwt.tokens import AccessToken

from inventory_apps.authentication.authentication import apply_workspace
from inventory_apps.authentication.models import User
from inventory_apps.authentication.platform import (
    PlatformLoginView, PlatformSelectWorkspaceView, PlatformSwitchView, SELECTION_SALT,
)
from inventory_apps.authentication.views import (
    RequestPasswordResetEmail, SetNewPasswordAPIView, VerifyResetCodeAPIView,
)
from inventory_apps.clients.models import Client, Domain, WorkspaceMembership
from inventory_apps.clients.workspaces import link_user, workspace_slug
from inventory_apps.erp_inventory.tests import InventoryTestBase
from inventory_apps.pos_app.models import Role, Store


class WorkspaceTestBase(InventoryTestBase):

    def setUp(self):
        super().setUp()
        self.store = Store.objects.create(name="Head Office", code="HQ", currency="NGN")
        self.user.store = self.store
        self.user.save(skip_validation=True, update_fields=["store"])
        self.member = User.objects.create_user(
            name="Ada Member", email="ada@workspace.test", password="pass1234", is_staff=True,
            role=Role.objects.get(name="owner"), store=self.store,
        )
        self.member.is_verified = True
        self.member.save(skip_validation=True)
        link_user(self.member, store_id=self.store.id, role_id=Role.objects.get(name="owner").id,
                  client=self.tenant)
        self.factory = RequestFactory()

    def login(self, email, password):
        request = self.factory.post("/platform/auth/login/", {"email": email, "password": password},
                                    content_type="application/json")
        return PlatformLoginView.as_view()(request)

    def select(self, token, subdomain):
        request = self.factory.post("/platform/auth/select-workspace/",
                                    {"selection_token": token, "subdomain": subdomain},
                                    content_type="application/json")
        return PlatformSelectWorkspaceView.as_view()(request)


class PlatformSignInTests(WorkspaceTestBase):

    def test_login_lists_the_businesses_then_selects_one_and_returns_tokens(self):
        response = self.login("ada@workspace.test", "pass1234")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data["workspaces"]), 1)
        slug = response.data["workspaces"][0]["subdomain"]
        self.assertEqual(slug, workspace_slug(self.tenant))
        self.assertEqual(response.data["workspaces"][0]["role"], "owner")

        chosen = self.select(response.data["selection_token"], slug)
        self.assertEqual(chosen.status_code, 200, chosen.data)
        self.assertEqual(chosen.data["subdomain"], slug)
        self.assertIn("access", chosen.data["tokens"])
        self.assertEqual(chosen.data["role"], "owner")

    def test_wrong_password_reveals_no_businesses(self):
        response = self.login("ada@workspace.test", "wrong-password")

        self.assertEqual(response.status_code, 401)
        self.assertNotIn("workspaces", response.data)

    def test_account_with_no_business_is_refused(self):
        User.objects.create_user(name="Lone", email="lone@workspace.test", password="pass1234",
                                 is_staff=True, role=Role.objects.get(name="owner"), store=self.store)
        User.objects.filter(email="lone@workspace.test").update(is_verified=True)

        response = self.login("lone@workspace.test", "pass1234")

        self.assertEqual(response.status_code, 403)
        self.assertIn("No business is linked", str(response.data))

    def test_selection_token_cannot_be_forged_and_cannot_pick_a_business_you_are_not_in(self):
        response = self.login("ada@workspace.test", "pass1234")
        token = response.data["selection_token"]

        forged = self.select(token + "x", workspace_slug(self.tenant))
        not_member = self.select(token, "nowhere")

        self.assertEqual(forged.status_code, 401)
        self.assertEqual(not_member.status_code, 403)

    def test_selection_token_is_bound_to_its_salt(self):
        bad = signing.TimestampSigner(salt="some-other-salt").sign_object({"uid": str(self.member.pk)})

        response = self.select(bad, workspace_slug(self.tenant))

        self.assertEqual(response.status_code, 401)


class PerBusinessAccessTests(WorkspaceTestBase):

    def test_a_second_business_gets_its_own_store_and_role(self):
        second = Client(schema_name="second_co", name="Second Co", contact_name="X", contact_email="x@second.test")
        second.auto_create_schema = False  # the test does not need a second schema
        with schema_context(get_public_schema_name()):
            second.save()
        Domain.objects.create(domain="second.lvh.me", tenant=second, is_primary=True)
        link_user(self.member, store_id=None, role_id=Role.objects.get(name="salesperson").id, client=second)

        response = self.login("ada@workspace.test", "pass1234")
        self.assertEqual(len(response.data["workspaces"]), 2)

        second_pick = self.select(response.data["selection_token"], "second")
        self.assertEqual(second_pick.status_code, 200, second_pick.data)
        self.assertEqual(second_pick.data["tenant"]["business_name"], "Second Co")
        # The role lives in the second business, so the membership carries its id, not the first business's.
        second_membership = WorkspaceMembership.objects.get(user=self.member, client=second)
        self.assertEqual(second_membership.role_id, Role.objects.get(name="salesperson").id)

    def test_a_user_linked_only_to_another_business_is_refused_here(self):
        other = Client(schema_name="elsewhere", name="Elsewhere", contact_name="X", contact_email="e@x.test")
        other.auto_create_schema = False
        with schema_context(get_public_schema_name()):
            other.save()
        outsider = User.objects.create_user(name="Out", email="out@workspace.test", password="pass1234",
                                            is_staff=True, role=Role.objects.get(name="owner"), store=self.store)
        link_user(outsider, store_id=None, role_id=None, client=other)

        with self.assertRaises(AuthenticationFailed):
            apply_workspace(outsider)

    def test_a_business_member_gets_the_store_and_role_of_this_business(self):
        apply_workspace(self.member)

        self.assertEqual(self.member.store_id, self.store.id)
        self.assertEqual(self.member.role.name, "owner")

    def test_inviting_a_member_records_their_business_membership(self):
        from unittest import mock
        with mock.patch("inventory_apps.authentication.views.Util.send_email", return_value=True), \
                mock.patch("inventory_apps.authentication.views.cache"):
            response = self.api.post("/auth/team/invite/", {
                "name": "New Hire", "email": "newhire@workspace.test",
                "role_id": str(Role.objects.get(name="salesperson").id),
            }, format="json")

        self.assertEqual(response.status_code, 201, response.data)
        invited = User.objects.get(email="newhire@workspace.test")
        membership = WorkspaceMembership.objects.get(user=invited, client=self.tenant)
        self.assertEqual(membership.role_id, Role.objects.get(name="salesperson").id)


class SwitchAndAttemptLimitTests(WorkspaceTestBase):
    """Limits and reset use an in-memory cache, so the tests do not need Redis."""

    def setUp(self):
        super().setUp()
        self.cache = LocMemCache("workspace-tests", {})  # locmem storage is shared by name, so clear it
        self.cache.clear()
        for target in (
            "inventory_apps.authentication.ratelimit.cache",
            "inventory_apps.authentication.views.cache",
            "inventory_apps.authentication.serializers.cache",
        ):
            patcher = mock.patch(target, self.cache)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_signed_in_user_can_list_businesses_to_switch_to(self):
        token = str(AccessToken.for_user(self.member))
        request = self.factory.post("/platform/auth/switch/", HTTP_AUTHORIZATION=f"Bearer {token}")

        response = PlatformSwitchView.as_view()(request)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["workspaces"][0]["subdomain"], workspace_slug(self.tenant))
        self.assertIn("selection_token", response.data)

    def test_switch_needs_a_signed_in_user(self):
        response = PlatformSwitchView.as_view()(self.factory.post("/platform/auth/switch/"))

        self.assertEqual(response.status_code, 401)

    def test_sign_in_is_limited_per_email(self):
        statuses = [self.login("ada@workspace.test", "wrong-password").status_code for _ in range(11)]

        self.assertEqual(statuses[:10], [401] * 10)
        self.assertEqual(statuses[10], 429)

    def test_a_correct_password_does_not_reset_the_limit_for_that_email(self):
        for _ in range(10):
            self.login("ada@workspace.test", "wrong-password")

        self.assertEqual(self.login("ada@workspace.test", "pass1234").status_code, 429)

    def test_reset_requests_are_limited_per_email(self):
        request_view = RequestPasswordResetEmail.as_view()
        statuses = []
        with mock.patch("inventory_apps.authentication.views.Util.send_email", return_value=True):
            for _ in range(6):
                request = self.factory.post("/platform/auth/password-reset/email/",
                                            {"email": "ada@workspace.test"}, content_type="application/json")
                statuses.append(request_view(request).status_code)

        self.assertEqual(statuses, [200] * 5 + [429])

    def test_password_can_be_reset_by_email_from_the_root_domain(self):
        with mock.patch("inventory_apps.authentication.views.Util.send_email", return_value=True):
            requested = RequestPasswordResetEmail.as_view()(self.factory.post(
                "/platform/auth/password-reset/email/", {"email": "ada@workspace.test"},
                content_type="application/json"))
        self.assertEqual(requested.status_code, 200)
        code = self.cache.get(f"password_reset_{self.member.pk}")["code"]

        verified = VerifyResetCodeAPIView.as_view()(self.factory.post(
            "/platform/auth/password-reset/verify/", {"email": "ada@workspace.test", "code": code},
            content_type="application/json"))
        self.assertEqual(verified.status_code, 200, verified.data)

        completed = SetNewPasswordAPIView.as_view()(self.factory.patch(
            "/platform/auth/password-reset/complete/",
            {"password": "brand-new-1234", "token": verified.data["reset_token"],
             "uidb64": verified.data["uidb64"]},
            content_type="application/json"))
        self.assertEqual(completed.status_code, 200, completed.data)

        self.assertEqual(self.login("ada@workspace.test", "brand-new-1234").status_code, 200)


class BusinessApprovalTests(WorkspaceTestBase):
    """A new business waits for a super admin; a deactivated one cannot be used."""

    def set_status(self, approval_status=None, active=None):
        from inventory_apps.clients import approval
        if approval_status == "pending":
            self.tenant.approval_status = "pending"
            self.tenant.save(update_fields=["approval_status"])
        if approval_status == "approved":
            approval.approve(self.tenant, by_email="admin@platform.test")
        if active is not None:
            approval.set_active(self.tenant, active)

    def token(self):
        return str(AccessToken.for_user(self.user))

    def call_with_token(self, path):
        """Send a real bearer token; the base test client is force-authenticated, which skips token checks."""
        self.api.force_authenticate(None)
        return self.api.get(path, HTTP_AUTHORIZATION=f"Bearer {self.token()}")

    def test_a_pending_business_refuses_sign_in_on_its_own_domain(self):
        self.set_status("pending")

        response = self.api.post("/auth/login/", {"email": self.user.email, "password": "pass1234"}, format="json")

        self.assertEqual(response.status_code, 403)
        self.assertIn("awaiting approval", str(response.data))

    def test_a_pending_business_refuses_a_token_that_was_issued_before(self):
        self.set_status("pending")

        response = self.call_with_token("/auth/me/")

        self.assertEqual(response.status_code, 403)

    def test_root_sign_in_says_why_a_business_is_not_open(self):
        self.set_status("pending")

        response = self.login("ada@workspace.test", "pass1234")

        self.assertEqual(response.status_code, 403)
        self.assertIn("awaiting approval", str(response.data))

    def test_approval_opens_the_business(self):
        self.set_status("pending")
        self.set_status("approved")

        response = self.call_with_token("/auth/me/")

        self.assertEqual(response.status_code, 200)

    def test_deactivating_stops_a_signed_in_user_at_once_and_reactivating_restores_them(self):
        self.assertEqual(self.call_with_token("/auth/me/").status_code, 200)

        self.set_status(active=False)
        self.assertEqual(self.call_with_token("/auth/me/").status_code, 403)

        self.set_status(active=True)
        self.assertEqual(self.call_with_token("/auth/me/").status_code, 200)

    def test_a_deactivated_business_is_left_out_of_the_business_list(self):
        self.set_status(active=False)

        response = self.login("ada@workspace.test", "pass1234")

        self.assertEqual(response.status_code, 403)
        self.assertIn("deactivated", str(response.data))
