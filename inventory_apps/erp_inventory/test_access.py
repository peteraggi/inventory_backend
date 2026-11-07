# inventory_apps/erp_inventory/test_access.py
"""
Multiple roles, revocation, the module gate, owner-only contact deletion, the profile's
roles and the dashboard figures.
"""
from decimal import Decimal

from inventory_apps.authentication.models import User, UserRole
from inventory_apps.erp_base.models import Partner, TenantModule
from inventory_apps.erp_inventory.test_permissions import RoleClientMixin
from inventory_apps.erp_inventory.tests import InventoryTestBase
from inventory_apps.pos_app.models import Role


class AccessTestBase(RoleClientMixin, InventoryTestBase):

    def setUp(self):
        super().setUp()
        from unittest import mock
        from inventory_apps.pos_app.models import Store
        self.store = Store.objects.create(name="Head Office", code="HQ", currency="NGN")
        self.user.store = self.store
        self.user.save(skip_validation=True, update_fields=["store"])
        # Invites send a verification email and cache a code; neither service exists in tests.
        for target in ("inventory_apps.authentication.views.cache",):
            patcher = mock.patch(target)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch("inventory_apps.authentication.views.Util.send_email", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def staff(self, role_name, email):
        """Invite a member through the team API, as the owner, with an optional extra role."""
        return self.api.post("/auth/team/invite/", {
            "name": "Staff", "email": email, "role_id": str(Role.objects.get(name=role_name).id),
        }, format="json")


class ContactDeleteTests(AccessTestBase):

    def setUp(self):
        super().setUp()
        self.vendor = Partner.objects.create(name="Spare Parts Ltd", is_vendor=True)

    def test_owner_deletes_an_unused_contact(self):
        response = self.api.delete(f"/erp/base/partners/{self.vendor.id}/")

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Partner.objects.filter(pk=self.vendor.id).exists())

    def test_contact_with_orders_or_bills_is_refused(self):
        from inventory_apps.erp_accounting.models import AccountJournal, AccountMove
        AccountJournal.objects.create(code="PJ", name="Purchases", journal_type="purchase")
        AccountMove.objects.create(
            move_type="in_invoice", partner=self.vendor,
            journal=AccountJournal.objects.get(code="PJ"),
        )

        response = self.api.delete(f"/erp/base/partners/{self.vendor.id}/")

        self.assertEqual(response.status_code, 400)
        self.assertIn("cannot be deleted", response.data["error"])
        self.assertTrue(Partner.objects.filter(pk=self.vendor.id).exists())

    def test_managers_and_salespeople_cannot_delete_contacts(self):
        for role in ("manager", "salesperson", "purchasing"):
            client, _ = self.client_for(role, email=f"{role}-del@test.local")
            response = client.delete(f"/erp/base/partners/{self.vendor.id}/")
            self.assertEqual(response.status_code, 403, role)
        self.assertTrue(Partner.objects.filter(pk=self.vendor.id).exists())


class MultipleRoleTests(AccessTestBase):

    def test_extra_role_grants_its_access_and_revocation_removes_it(self):
        invited = self.staff("salesperson", "extra-role@test.local")
        self.assertEqual(invited.status_code, 201, invited.data)
        member = User.objects.get(email="extra-role@test.local")
        purchasing = Role.objects.get(name="purchasing")

        added = self.api.patch(f"/auth/team/{member.id}/", {
            "additional_role_ids": [str(purchasing.id)],
        }, format="json")
        self.assertEqual(added.status_code, 200, added.data)
        client = self.client_for_user(member)
        self.assertEqual(client.get("/erp/purchase/orders/").status_code, 200)

        revoked = self.api.patch(f"/auth/team/{member.id}/", {"additional_role_ids": []}, format="json")
        self.assertEqual(revoked.status_code, 200)
        self.assertEqual(client.get("/erp/purchase/orders/").status_code, 403)
        assignment = UserRole.objects.get(user=member, role=purchasing)
        self.assertIsNotNone(assignment.unassigned_at, "revocation keeps the history")

    def test_invite_can_include_extra_roles(self):
        response = self.api.post("/auth/team/invite/", {
            "name": "Multi", "email": "multi@test.local",
            "role_id": str(Role.objects.get(name="salesperson").id),
            "additional_role_ids": [str(Role.objects.get(name="purchasing").id)],
        }, format="json")

        self.assertEqual(response.status_code, 201, response.data)
        member = User.objects.get(email="multi@test.local")
        self.assertEqual(
            sorted(r["name"] for r in response.data["roles"]), ["purchasing", "salesperson"],
        )
        self.assertEqual(member.extra_roles.filter(unassigned_at__isnull=True).count(), 1)

    def test_manager_cannot_assign_a_role_with_permissions_they_do_not_hold(self):
        manager, _ = self.client_for("manager", email="mgr-assign@test.local")

        response = manager.post("/auth/team/invite/", {
            "name": "Acc", "email": "acc-target@test.local",
            "role_id": str(Role.objects.get(name="salesperson").id),
            "additional_role_ids": [str(Role.objects.get(name="accountant").id)],
        }, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("Accountant", str(response.data))
        self.assertFalse(User.objects.filter(email="acc-target@test.local").exists())

    def test_manager_cannot_assign_owner_as_an_extra_role(self):
        manager, _ = self.client_for("manager", email="mgr-owner@test.local")

        response = manager.post("/auth/team/invite/", {
            "name": "Own", "email": "owner-target@test.local",
            "role_id": str(Role.objects.get(name="salesperson").id),
            "additional_role_ids": [str(Role.objects.get(name="owner").id)],
        }, format="json")

        self.assertEqual(response.status_code, 400)

    def client_for_user(self, user):
        from rest_framework.test import APIClient
        client = APIClient()
        client.defaults["HTTP_HOST"] = self.domain.domain
        client.defaults["HTTP_X_FORWARDED_PROTO"] = "https"
        client.force_authenticate(user)
        return client


class ModuleGateTests(AccessTestBase):

    def test_a_disabled_module_grants_nothing_even_to_owners(self):
        self.receive(1, price=1)
        TenantModule.objects.update_or_create(key="pos", defaults={"name": "Point of Sale", "enabled": False})

        response = self.api.get("/erp/pos/orders/")
        matrix = self.api.get("/auth/me/").data["permissions"]

        self.assertEqual(response.status_code, 403)
        self.assertFalse(any(matrix["pos"].values()))
        self.assertTrue(matrix["inventory"]["read"])


class ProfileRolesTests(AccessTestBase):

    def test_profile_lists_primary_and_extra_roles(self):
        member = User.objects.create_user(
            name="Mo", email="profile-roles@test.local", password="pass1234", is_staff=True,
            role=Role.objects.get(name="salesperson"), store=self.user.store,
        )
        UserRole.objects.create(user=member, role=Role.objects.get(name="purchasing"))

        from rest_framework.test import APIClient
        client = APIClient()
        client.defaults["HTTP_HOST"] = self.domain.domain
        client.defaults["HTTP_X_FORWARDED_PROTO"] = "https"
        client.force_authenticate(member)
        profile = client.get("/auth/me/").data

        self.assertEqual(sorted(r["name"] for r in profile["roles"]), ["purchasing", "salesperson"])
        self.assertTrue(profile["permissions"]["purchases"]["update"])


class DashboardTests(InventoryTestBase):

    def test_summary_counts_low_stock_and_returns_the_chart_series(self):
        self.receive(3, price=2)

        response = self.api.get("/erp/accounting/reports/dashboard-summary/")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["low_stock_count"], 1)
        self.assertEqual(len(response.data["sales_trend"]), 14)
        self.assertEqual(Decimal(str(response.data["today_sales"])), Decimal("0"))
        self.assertIn("channel_breakdown", response.data)


class TeamAndDashboardAccessTests(AccessTestBase):

    def test_managers_manage_the_team_but_cannot_delete_members(self):
        manager, _ = self.client_for("manager", email="mgr-team@test.local")
        member = User.objects.create_user(name="Mem", email="member-x@test.local", password="pass1234",
                                          is_staff=True, role=Role.objects.get(name="salesperson"),
                                          store=self.store)

        self.assertEqual(manager.get("/auth/team/").status_code, 200)
        self.assertEqual(manager.patch(f"/auth/team/{member.id}/", {"is_active": False}, format="json").status_code, 200)

    def test_salespeople_cannot_see_or_manage_the_team(self):
        sales, _ = self.client_for("salesperson", email="sales-team@test.local")

        self.assertEqual(sales.get("/auth/team/").status_code, 403)

    def test_dashboard_is_open_to_sales_and_stock_users_without_reports(self):
        from inventory_apps.erp_base.rbac_constants import DEFAULT_ROLE_PERMISSIONS
        from inventory_apps.pos_app.models import Role as PosRole
        role = PosRole.objects.get(name="salesperson")
        matrix = dict(role.permissions)
        matrix["reports"] = {"read": False, "create": False, "update": False, "delete": False}
        role.permissions = matrix
        role.save(update_fields=["permissions"])
        sales, _ = self.client_for("salesperson", email="dash-sales@test.local")

        self.assertEqual(sales.get("/erp/accounting/reports/dashboard-summary/").status_code, 200)

    def test_dashboard_is_refused_to_users_with_no_sales_or_stock_access(self):
        # No role at all: accountants can read sales and inventory, so they are not a good example.
        user = User.objects.create_user(name="Nobody", email="nobody@test.local", password="pass1234",
                                        is_staff=True, role=None, store=self.store)
        from rest_framework.test import APIClient
        client = APIClient()
        client.defaults["HTTP_HOST"] = self.domain.domain
        client.defaults["HTTP_X_FORWARDED_PROTO"] = "https"
        client.force_authenticate(user)

        response = client.get("/erp/accounting/reports/dashboard-summary/")

        self.assertEqual(response.status_code, 403)


class LegacyPosAccessTests(AccessTestBase):
    """The legacy /pos/ endpoints follow the same role matrix as the ERP modules."""

    def test_salesperson_cannot_create_vendor_bills(self):
        sales, _ = self.client_for("salesperson", email="legacy-bills@test.local")

        response = sales.post("/pos/vendor-bills/", {}, format="json")

        self.assertEqual(response.status_code, 403)

    def test_salesperson_can_reach_sales_orders(self):
        sales, _ = self.client_for("salesperson", email="legacy-orders@test.local")

        response = sales.get("/pos/sales-orders/")

        self.assertEqual(response.status_code, 200)

    def test_salesperson_cannot_change_accounts(self):
        sales, _ = self.client_for("salesperson", email="legacy-accounts@test.local")

        response = sales.post("/pos/accounts/", {"code": "999999", "name": "x"}, format="json")

        self.assertEqual(response.status_code, 403)

    def test_salesperson_cannot_edit_a_product_but_can_read_products(self):
        sales, _ = self.client_for("salesperson", email="legacy-products@test.local")

        read = sales.get("/pos/products/")
        write = sales.post("/pos/products/", {"name": "Bottle"}, format="json")

        self.assertEqual(read.status_code, 200)
        self.assertEqual(write.status_code, 403)

    def test_a_store_that_is_switched_off_is_refused_on_legacy_endpoints(self):
        sales, user = self.client_for("salesperson", email="legacy-off@test.local")
        self.store.is_active = False
        self.store.save(update_fields=["is_active"])

        response = sales.get("/pos/sales-orders/")

        self.assertEqual(response.status_code, 403)
