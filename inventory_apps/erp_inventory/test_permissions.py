# inventory_apps/erp_inventory/test_permissions.py
from decimal import Decimal

from django.test import RequestFactory
from rest_framework.test import APIClient

from inventory_apps.authentication.models import User
from inventory_apps.authentication.serializers import TeamMemberInviteSerializer, TeamMemberUpdateSerializer
from inventory_apps.erp_inventory.tests import InventoryTestBase
from inventory_apps.pos_app.models import Role


class RoleClientMixin:
    """Builds an API client signed in as a user holding the given role."""

    def client_for(self, role_name, overrides=None, email=None):
        user = User.objects.create_user(
            name=role_name.title(),
            email=email or f"{role_name}@test.local",
            password="pass1234",
            is_staff=True,
            role=Role.objects.get(name=role_name),
            store=getattr(self, "store", None),
        )
        if overrides:
            user.permission_overrides = overrides
            user.save(skip_validation=True, update_fields=["permission_overrides"])
        client = APIClient()
        client.defaults["HTTP_HOST"] = self.domain.domain
        client.defaults["HTTP_X_FORWARDED_PROTO"] = "https"
        client.force_authenticate(user)
        return client, user


class InventoryPermissionTests(RoleClientMixin, InventoryTestBase):

    def new_picking(self):
        """A confirmed receipt created as the owner, ready for someone else to validate."""
        response = self.api.post("/erp/inventory/pickings/", {
            "picking_type": str(self.receipt_type.id),
            "location_src": str(self.vendor_loc.id),
            "location_dest": str(self.stock_loc.id),
            "move_lines": [{"product": str(self.product.id), "product_uom_qty": "4"}],
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.api.post(f"/erp/inventory/pickings/{response.data['id']}/confirm/", {}, format="json")
        return response.data["id"]

    def test_salesperson_can_read_inventory(self):
        self.receive(3)
        sales, _ = self.client_for("salesperson")

        self.assertEqual(sales.get("/erp/inventory/pickings/").status_code, 200)
        self.assertEqual(sales.get("/erp/inventory/quants/").status_code, 200)

    def test_salesperson_cannot_validate_a_transfer(self):
        picking_id = self.new_picking()
        sales, _ = self.client_for("salesperson")

        response = sales.post(f"/erp/inventory/pickings/{picking_id}/validate/", {}, format="json")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.on_hand(), Decimal("0"))

    def test_salesperson_cannot_post_a_physical_count(self):
        sales, _ = self.client_for("salesperson")

        response = sales.post("/erp/inventory/quants/apply/", {"quants": []}, format="json")

        self.assertEqual(response.status_code, 403)

    def test_salesperson_cannot_create_scrap(self):
        sales, _ = self.client_for("salesperson")

        response = sales.post("/erp/inventory/scrap/", {"product": str(self.product.id), "quantity": 1}, format="json")

        self.assertEqual(response.status_code, 403)

    def test_user_grant_adds_access_on_top_of_the_role(self):
        picking_id = self.new_picking()
        sales, _ = self.client_for("salesperson", overrides={"inventory": {"update": True}})

        response = sales.post(f"/erp/inventory/pickings/{picking_id}/validate/", {}, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.on_hand(), Decimal("4"))

    def test_manager_runs_stock_workflows(self):
        picking_id = self.new_picking()
        manager, _ = self.client_for("manager")

        response = manager.post(f"/erp/inventory/pickings/{picking_id}/validate/", {}, format="json")

        self.assertEqual(response.status_code, 200, response.data)

    def test_user_without_role_is_denied(self):
        user = User.objects.create_user(
            name="No Role", email="norole@test.local", password="pass1234", is_staff=True,
        )
        client = APIClient()
        client.defaults["HTTP_HOST"] = self.domain.domain
        client.defaults["HTTP_X_FORWARDED_PROTO"] = "https"
        client.force_authenticate(user)

        self.assertEqual(client.get("/erp/inventory/warehouses/").status_code, 403)

    def test_anonymous_requests_are_rejected(self):
        anonymous = APIClient()
        anonymous.defaults["HTTP_HOST"] = self.domain.domain
        anonymous.defaults["HTTP_X_FORWARDED_PROTO"] = "https"

        self.assertIn(anonymous.get("/erp/inventory/warehouses/").status_code, (401, 403))


class RolePermissionTests(RoleClientMixin, InventoryTestBase):

    def role_url(self):
        return f"/pos/roles/{Role.objects.get(name='salesperson').id}/"

    def test_role_list_requires_sign_in(self):
        anonymous = APIClient()
        anonymous.defaults["HTTP_HOST"] = self.domain.domain
        anonymous.defaults["HTTP_X_FORWARDED_PROTO"] = "https"

        self.assertIn(anonymous.get("/pos/roles/").status_code, (401, 403))

    def test_manager_cannot_edit_role_permissions(self):
        manager, _ = self.client_for("manager")

        response = manager.patch(self.role_url(), {"permissions": {"sales": {"read": True}}}, format="json")

        self.assertEqual(response.status_code, 403)

    def test_owner_can_edit_role_permissions(self):
        response = self.api.patch(self.role_url(), {"permissions": {"inventory": {"read": True}}}, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(Role.objects.get(name="salesperson").permissions, {"inventory": {"read": True}})

    def test_role_matrix_with_unknown_keys_is_rejected(self):
        response = self.api.patch(self.role_url(), {"permissions": {"invntory": {"read": True}}}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("Unknown resource 'invntory'.", str(response.data))


class TeamDelegationTests(RoleClientMixin, InventoryTestBase):

    def request_for(self, user):
        request = RequestFactory().post("/auth/team/invite/")
        request.user = user
        return request

    def invite_payload(self, role_name, overrides=None):
        return {
            "name": "New Hire",
            "email": f"hire-{role_name}-{len(overrides or {})}@test.local",
            "role_id": str(Role.objects.get(name=role_name).id),
            "permission_overrides": overrides or {},
        }

    def test_salesperson_cannot_invite_staff(self):
        sales, _ = self.client_for("salesperson")

        response = sales.post("/auth/team/invite/", self.invite_payload("salesperson"), format="json")

        self.assertEqual(response.status_code, 403)

    def test_manager_cannot_assign_the_owner_role(self):
        _, manager = self.client_for("manager")
        serializer = TeamMemberInviteSerializer(
            data=self.invite_payload("owner"), context={"request": self.request_for(manager)},
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("role_id", serializer.errors)

    def test_manager_cannot_grant_what_they_do_not_hold(self):
        _, manager = self.client_for("manager")
        serializer = TeamMemberInviteSerializer(
            data=self.invite_payload("salesperson", {"settings": {"update": True}}),
            context={"request": self.request_for(manager)},
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("permission_overrides", serializer.errors)

    def test_manager_can_grant_what_they_hold_and_only_true_grants_are_stored(self):
        _, manager = self.client_for("manager")
        serializer = TeamMemberInviteSerializer(
            data=self.invite_payload("salesperson", {"inventory": {"read": True, "delete": False}}),
            context={"request": self.request_for(manager)},
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["permission_overrides"], {"inventory": {"read": True}})

    def test_manager_cannot_change_an_owner_account(self):
        manager, _ = self.client_for("manager")
        owner = User.objects.get(email="inventory@test.local")

        response = manager.patch(f"/auth/team/{owner.id}/", {"is_active": False}, format="json")

        self.assertEqual(response.status_code, 403)
        owner.refresh_from_db()
        self.assertTrue(owner.is_active)

    def test_update_serializer_applies_the_same_grant_rule(self):
        _, manager = self.client_for("manager")
        serializer = TeamMemberUpdateSerializer(
            data={"permission_overrides": {"accounting": {"delete": True}}},
            context={"request": self.request_for(manager)},
        )

        self.assertFalse(serializer.is_valid())


class EffectivePermissionsTests(RoleClientMixin, InventoryTestBase):

    def test_me_reports_role_plus_individual_grants(self):
        sales, _ = self.client_for("salesperson", overrides={"inventory": {"update": True}})

        matrix = sales.get("/auth/me/").data["permissions"]

        self.assertTrue(matrix["inventory"]["update"])  # individual grant
        self.assertTrue(matrix["sales"]["create"])      # from the role
        self.assertFalse(matrix["accounting"]["read"])  # neither

    def test_me_reports_full_access_for_owner(self):
        matrix = self.api.get("/auth/me/").data["permissions"]

        self.assertTrue(all(all(actions.values()) for actions in matrix.values()))


class RolePermissionRepairTests(InventoryTestBase):

    def test_legacy_flat_roles_are_replaced_and_matrices_are_kept(self):
        import importlib
        from django.apps import apps as global_apps
        from inventory_apps.erp_base.rbac_constants import DEFAULT_ROLE_PERMISSIONS

        migration = importlib.import_module("inventory_apps.pos_app.migrations.0003_sync_role_permissions")
        owner = Role.objects.get(name="owner")
        owner.permissions = {"manage_users": True, "manage_store": True}
        owner.save(update_fields=["permissions"])
        custom = {"inventory": {"read": True}}
        manager = Role.objects.get(name="manager")
        manager.permissions = custom
        manager.save(update_fields=["permissions"])

        migration.sync_role_permissions(global_apps, None)

        owner.refresh_from_db()
        manager.refresh_from_db()
        self.assertEqual(owner.permissions, DEFAULT_ROLE_PERMISSIONS["owner"])
        self.assertEqual(manager.permissions, custom)


class MemberAccessEditTests(RoleClientMixin, InventoryTestBase):

    def test_owner_sets_member_grants_and_they_are_listed(self):
        member = User.objects.create_user(
            name="Mo Member", email="member@test.local", password="pass1234", is_staff=True,
            role=Role.objects.get(name="salesperson"), store=self.user.store,
        )

        response = self.api.patch(f"/auth/team/{member.id}/", {
            "permission_overrides": {"inventory": {"update": True}},
        }, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        listed = self.api.get("/auth/team/").data["results"]
        row = next(r for r in listed if r["id"] == str(member.id))
        # Write implies read, so the stored grant includes read as well.
        self.assertEqual(row["permission_overrides"], {"inventory": {"read": True, "update": True}})
