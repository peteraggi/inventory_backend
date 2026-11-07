# inventory_apps/erp_inventory/tests.py
from decimal import Decimal

from django.utils.dateparse import parse_datetime
from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient

from inventory_apps.authentication.models import User
from inventory_apps.erp_base.rbac_constants import DEFAULT_ROLE_DESCRIPTIONS, DEFAULT_ROLE_PERMISSIONS
from inventory_apps.pos_app.models import Role
from inventory_apps.erp_base.models import ProductTemplate
from inventory_apps.erp_inventory.models import (
    ReorderingRule, ScrapOrder, StockInventoryAdjustment, StockInventoryAdjustmentLine,
    StockMove, StockPicking, StockQuant, Warehouse,
)
from inventory_apps.notifications.models import Notification


def seed_roles():
    """Create the preset roles with their default permission matrices, as tenant creation does."""
    for name, display_name in Role.ROLE_CHOICES:
        Role.objects.get_or_create(
            name=name,
            defaults={
                "display_name": display_name,
                "description": DEFAULT_ROLE_DESCRIPTIONS.get(name, ""),
                "permissions": DEFAULT_ROLE_PERMISSIONS.get(name, {}),
            },
        )


class InventoryTestBase(TenantTestCase):
    """Runs each test in its own tenant schema, calling the API as an authenticated user."""

    def setUp(self):
        seed_roles()
        self.user = User.objects.create_user(
            name="Inventory Tester", email="inventory@test.local", password="pass1234", is_staff=True,
            role=Role.objects.get(name="owner"),
        )
        self.api = APIClient()
        self.api.defaults["HTTP_HOST"] = self.domain.domain
        # Production sits behind a TLS proxy (SECURE_PROXY_SSL_HEADER) with SECURE_SSL_REDIRECT on.
        self.api.defaults["HTTP_X_FORWARDED_PROTO"] = "https"
        self.api.force_authenticate(self.user)

        self.warehouse = Warehouse.objects.create(name="Main", short_name="WH")
        self.receipt_type = self.warehouse.picking_types.get(code="incoming")
        self.stock_loc = self.warehouse.lot_stock_location
        self.vendor_loc = self.receipt_type.default_location_src

        template = ProductTemplate.objects.create(name="Widget", internal_reference="W-1")
        self.product = template.variants.first()

    def receive(self, qty, price=None):
        """Create and validate a receipt of `qty` units into stock via the API."""
        line = {"product": str(self.product.id), "product_uom_qty": str(qty)}
        if price is not None:
            line["price_unit"] = str(price)
        response = self.api.post("/erp/inventory/pickings/", {
            "picking_type": str(self.receipt_type.id),
            "location_src": str(self.vendor_loc.id),
            "location_dest": str(self.stock_loc.id),
            "move_lines": [line],
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        picking_id = response.data["id"]
        self.api.post(f"/erp/inventory/pickings/{picking_id}/confirm/", {}, format="json")
        response = self.api.post(f"/erp/inventory/pickings/{picking_id}/validate/", {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        return picking_id

    def on_hand(self, location=None):
        quant = StockQuant.objects.filter(product=self.product, location=location or self.stock_loc).first()
        return quant.quantity if quant else Decimal("0")


class PickingFlowTests(InventoryTestBase):

    def test_validate_receipt_moves_stock_and_notifies_user(self):
        picking_id = self.receive(10)

        self.assertEqual(self.on_hand(), Decimal("10"))
        self.assertEqual(StockPicking.objects.get(pk=picking_id).state, "done")
        notice = Notification.objects.get(user=self.user)
        self.assertEqual(notice.notification_type, "PICKING_VALIDATED")
        self.assertFalse(notice.is_read)

    def test_cancel_picking_notifies_user(self):
        response = self.api.post("/erp/inventory/pickings/", {
            "picking_type": str(self.receipt_type.id),
            "location_src": str(self.vendor_loc.id),
            "location_dest": str(self.stock_loc.id),
            "move_lines": [{"product": str(self.product.id), "product_uom_qty": "3"}],
        }, format="json")
        picking_id = response.data["id"]

        response = self.api.post(f"/erp/inventory/pickings/{picking_id}/cancel/", {}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(StockPicking.objects.get(pk=picking_id).state, "cancel")
        self.assertTrue(Notification.objects.filter(user=self.user, notification_type="PICKING_CANCELLED").exists())

    def test_invalid_picking_returns_envelope_with_field_name(self):
        response = self.api.post("/erp/inventory/pickings/", {
            "picking_type": str(self.receipt_type.id),
            "location_dest": str(self.stock_loc.id),
        }, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["error"], "location_src: This field is required.")
        self.assertIn("location_src", response.data["details"])

    def test_missing_resource_returns_envelope(self):
        response = self.api.get("/erp/inventory/pickings/00000000-0000-0000-0000-000000000000/")

        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.data["success"])
        self.assertIn("error", response.data)

    def test_operation_types_route_lists_warehouse_types(self):
        response = self.api.get("/erp/inventory/operation-types/")

        self.assertEqual(response.status_code, 200)
        codes = {row["code"] for row in response.data["results"]}
        self.assertEqual(codes, {"incoming", "outgoing", "internal"})

    def test_move_lines_expose_report_fields(self):
        self.receive(4)

        response = self.api.get("/erp/inventory/move-lines/", {"state": "done"})

        self.assertEqual(response.status_code, 200)
        row = response.data["results"][0]
        for field in ("date", "reference", "qty_done", "picking_name", "product_name", "lot_name"):
            self.assertIn(field, row)
        self.assertEqual(Decimal(row["qty_done"]), Decimal("4.0000"))

    def test_move_lines_date_range_filter(self):
        self.receive(2)

        response = self.api.get("/erp/inventory/move-lines/", {"date_from": "2999-01-01"})

        self.assertEqual(response.data["count"], 0)


class PhysicalCountTests(InventoryTestBase):

    def test_apply_count_sets_quantity_and_notifies(self):
        self.receive(10)
        quant = StockQuant.objects.get(product=self.product, location=self.stock_loc)

        response = self.api.post("/erp/inventory/quants/apply/", {
            "quants": [{"quant_id": str(quant.id), "inventory_quantity": "7"}],
        }, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["applied"], 1)
        self.assertEqual(self.on_hand(), Decimal("7"))
        self.assertTrue(Notification.objects.filter(user=self.user, notification_type="STOCK_COUNT_APPLIED").exists())

    def test_apply_count_unknown_quant_returns_error(self):
        response = self.api.post("/erp/inventory/quants/apply/", {
            "quants": [{"quant_id": "00000000-0000-0000-0000-000000000001", "inventory_quantity": "1"}],
        }, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data["success"])
        self.assertIn("does not exist", response.data["error"])

    def test_apply_count_rejects_empty_payload(self):
        response = self.api.post("/erp/inventory/quants/apply/", {"quants": []}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data["success"])


class AdjustmentTests(InventoryTestBase):

    def test_adjustment_validate_posts_difference_once(self):
        self.receive(5)
        adjustment = StockInventoryAdjustment.objects.create(location=self.stock_loc)
        StockInventoryAdjustmentLine.objects.create(
            adjustment=adjustment, product=self.product,
            theoretical_qty=Decimal("5"), inventory_qty=Decimal("8"),
        )

        response = self.api.post(f"/erp/inventory/adjustments/{adjustment.id}/validate/", {}, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.on_hand(), Decimal("8"))
        self.assertTrue(Notification.objects.filter(user=self.user, notification_type="ADJUSTMENT_VALIDATED").exists())

        again = self.api.post(f"/erp/inventory/adjustments/{adjustment.id}/validate/", {}, format="json")
        self.assertEqual(again.status_code, 400)
        self.assertEqual(again.data["error"], "Adjustment already validated")
        self.assertEqual(self.on_hand(), Decimal("8"))


class NullLotQuantTests(InventoryTestBase):

    def test_only_one_quant_per_product_location_without_lot(self):
        from django.db import IntegrityError, transaction

        StockQuant.objects.create(product=self.product, location=self.stock_loc, quantity=Decimal("1"))
        with self.assertRaises(IntegrityError), transaction.atomic():
            StockQuant.objects.create(product=self.product, location=self.stock_loc, quantity=Decimal("2"))


class NotificationApiTests(InventoryTestBase):

    def test_unread_count_and_mark_all_read(self):
        self.receive(1)
        self.receive(2)

        count = self.api.get("/notifications/unread_count/")
        self.assertEqual(count.data["unread_count"], 2)

        marked = self.api.post("/notifications/mark_all_as_read/", {}, format="json")
        self.assertEqual(marked.data["count"], 2)
        self.assertEqual(self.api.get("/notifications/unread_count/").data["unread_count"], 0)

    def test_users_only_see_their_own_notifications(self):
        self.receive(1)
        other = User.objects.create_user(name="Other", email="other@test.local", password="pass1234", is_staff=True)
        Notification.objects.create(user=other, title="Not yours", message="x")

        response = self.api.get("/notifications/")

        self.assertEqual(response.data["count"], 1)
        self.assertNotEqual(response.data["results"][0]["title"], "Not yours")


class ReturnTests(InventoryTestBase):

    def test_return_reverses_locations_and_restores_stock(self):
        picking_id = self.receive(6)

        response = self.api.post(f"/erp/inventory/pickings/{picking_id}/return/", {}, format="json")

        self.assertEqual(response.status_code, 201, response.data)
        returned = StockPicking.objects.get(pk=response.data["id"])
        self.assertEqual(returned.state, "confirmed")
        self.assertEqual(returned.location_src, self.stock_loc)
        self.assertEqual(returned.location_dest, self.vendor_loc)
        self.assertEqual(returned.picking_type.code, "outgoing")

        self.api.post(f"/erp/inventory/pickings/{returned.id}/validate/", {}, format="json")
        self.assertEqual(self.on_hand(), Decimal("0"))

    def test_return_requires_a_done_transfer(self):
        response = self.api.post("/erp/inventory/pickings/", {
            "picking_type": str(self.receipt_type.id),
            "location_src": str(self.vendor_loc.id),
            "location_dest": str(self.stock_loc.id),
            "move_lines": [{"product": str(self.product.id), "product_uom_qty": "2"}],
        }, format="json")

        response = self.api.post(f"/erp/inventory/pickings/{response.data['id']}/return/", {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"], "Only done transfers can be returned")


class ScrapTests(InventoryTestBase):

    def test_scrap_moves_stock_to_scrap_location_on_validate(self):
        self.receive(10)
        response = self.api.post("/erp/inventory/scrap/", {
            "product": str(self.product.id), "quantity": 3, "origin": "Damaged",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["state"], "draft")
        self.assertEqual(response.data["product_name"], "Widget")

        response = self.api.post(f"/erp/inventory/scrap/{response.data['id']}/validate/", {}, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["state"], "done")
        self.assertEqual(self.on_hand(), Decimal("7"))
        scrapped = StockQuant.objects.get(product=self.product, location__usage="inventory")
        self.assertEqual(scrapped.quantity, Decimal("3"))
        self.assertTrue(Notification.objects.filter(user=self.user, notification_type="SCRAP_VALIDATED").exists())

    def test_scrap_refuses_more_than_available_and_double_validation(self):
        self.receive(2)
        scrap = self.api.post("/erp/inventory/scrap/", {"product": str(self.product.id), "quantity": 5}, format="json")

        response = self.api.post(f"/erp/inventory/scrap/{scrap.data['id']}/validate/", {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("Insufficient stock", response.data["error"])
        self.assertEqual(self.on_hand(), Decimal("2"))
        self.assertEqual(ScrapOrder.objects.get(pk=scrap.data["id"]).state, "draft")

    def test_scrap_rejects_non_positive_quantity(self):
        response = self.api.post("/erp/inventory/scrap/", {"product": str(self.product.id), "quantity": 0}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("quantity", response.data["details"])


class ForecastTests(InventoryTestBase):

    def test_forecast_adds_pending_receipts_to_on_hand(self):
        self.receive(10)
        self.api.post("/erp/inventory/pickings/", {
            "picking_type": str(self.receipt_type.id),
            "location_src": str(self.vendor_loc.id),
            "location_dest": str(self.stock_loc.id),
            "move_lines": [{"product": str(self.product.id), "product_uom_qty": "5"}],
        }, format="json")

        response = self.api.get("/erp/inventory/forecast/", {"warehouse": str(self.warehouse.id)})

        self.assertEqual(response.status_code, 200)
        row = next(r for r in response.data["results"] if r["product_id"] == str(self.product.id))
        self.assertEqual(Decimal(row["qty_on_hand"]), Decimal("10"))
        self.assertEqual(Decimal(row["incoming_qty"]), Decimal("5"))
        self.assertEqual(Decimal(row["outgoing_qty"]), Decimal("0"))
        self.assertEqual(Decimal(row["forecasted_qty"]), Decimal("15"))
        self.assertEqual(row["warehouse_name"], "Main")


class ReplenishmentTests(InventoryTestBase):

    def setUp(self):
        super().setUp()
        self.rule_response = self.api.post("/erp/inventory/reordering-rules/", {
            "product": str(self.product.id),
            "location": str(self.stock_loc.id),
            "product_min_qty": "5",
            "product_max_qty": "20",
            "qty_multiple": "4",
        }, format="json")

    def test_rule_uses_frontend_field_names_and_derives_warehouse(self):
        self.assertEqual(self.rule_response.status_code, 201, self.rule_response.data)
        self.assertEqual(self.rule_response.data["product_min_qty"], "5.0000")
        self.assertEqual(Decimal(self.rule_response.data["qty_on_hand"]), Decimal("0"))
        self.assertEqual(self.rule_response.data["route_name"], "Buy")
        self.assertEqual(ReorderingRule.objects.get().warehouse, self.warehouse)

    def test_replenish_creates_receipt_up_to_max_rounded_to_multiple(self):
        response = self.api.post("/erp/inventory/reordering-rules/replenish/", {}, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["created"], 1)
        receipt = StockPicking.objects.get(origin="Replenishment")
        self.assertEqual(receipt.state, "confirmed")
        move = receipt.move_lines.get()
        self.assertEqual(move.product_uom_qty, Decimal("20"))
        self.assertTrue(Notification.objects.filter(user=self.user, notification_type="REPLENISHMENT_CREATED").exists())

    def test_replenish_does_nothing_when_incoming_already_covers_minimum(self):
        self.api.post("/erp/inventory/reordering-rules/replenish/", {}, format="json")

        second = self.api.post("/erp/inventory/reordering-rules/replenish/", {}, format="json")

        self.assertEqual(second.data["created"], 0)
        self.assertEqual(StockPicking.objects.filter(origin="Replenishment").count(), 1)


class LedgerValuationTests(InventoryTestBase):

    def deliver(self, qty):
        """Create and validate a delivery of `qty` units to the customer location."""
        delivery_type = self.warehouse.picking_types.get(code="outgoing")
        response = self.api.post("/erp/inventory/pickings/", {
            "picking_type": str(delivery_type.id),
            "location_src": str(self.stock_loc.id),
            "location_dest": str(delivery_type.default_location_dest.id),
            "move_lines": [{"product": str(self.product.id), "product_uom_qty": str(qty)}],
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.api.post(f"/erp/inventory/pickings/{response.data['id']}/confirm/", {}, format="json")
        response = self.api.post(f"/erp/inventory/pickings/{response.data['id']}/validate/", {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)

    def test_every_change_writes_a_ledger_row(self):
        from inventory_apps.erp_inventory.models import StockLedgerEntry

        self.receive(10)

        entry = StockLedgerEntry.objects.get(location=self.stock_loc, change_type="RECEIPT")
        self.assertEqual(entry.quantity_change, Decimal("10"))
        self.assertEqual(entry.resulting_quantity, Decimal("10"))
        self.assertEqual(entry.reference_type, "TRANSFER")
        self.assertEqual(entry.reference_name, StockPicking.objects.get().name)

    def test_fifo_consumes_oldest_layers_first(self):
        from inventory_apps.erp_inventory.models import StockLedgerEntry

        self.receive(10, price=5)
        self.receive(10, price=8)
        self.deliver(15)

        # 10 @ 5 + 5 @ 8 = 90 over 15 units
        delivery = StockLedgerEntry.objects.get(change_type="DELIVERY", location=self.stock_loc)
        self.assertEqual(delivery.unit_cost, Decimal("6.0000"))
        self.assertEqual(delivery.resulting_quantity, Decimal("5"))

        valuation = self.api.get("/erp/inventory/valuation/", {"warehouse": str(self.warehouse.id)})
        self.assertEqual(valuation.data["count"], 1)
        self.assertEqual(Decimal(valuation.data["results"][0]["quantity"]), Decimal("5"))
        self.assertEqual(Decimal(valuation.data["total_value"]), Decimal("40"))

    def test_nrv_caps_cost_at_sale_price_once(self):
        from inventory_apps.erp_base.models import ProductTemplate
        from inventory_apps.erp_inventory.models import InventoryNrvAdjustment

        ProductTemplate.objects.filter(pk=self.product.product_template_id).update(sale_price=Decimal("6"))
        self.receive(5, price=8)

        first = self.api.post("/erp/inventory/nrv/", {}, format="json")
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(first.data["created"], 1)

        adjustment = InventoryNrvAdjustment.objects.get()
        self.assertEqual(adjustment.per_unit_adjustment, Decimal("2.0000"))
        self.assertEqual(adjustment.total_adjustment, Decimal("10.0000"))

        value = self.api.get("/erp/inventory/valuation/")
        self.assertEqual(Decimal(value.data["total_value"]), Decimal("30"))

        second = self.api.post("/erp/inventory/nrv/", {}, format="json")
        self.assertEqual(second.data["created"], 0)

    def test_nrv_list_shows_recorded_write_downs(self):
        from inventory_apps.erp_base.models import ProductTemplate

        ProductTemplate.objects.filter(pk=self.product.product_template_id).update(sale_price=Decimal("1"))
        self.receive(4, price=3)
        self.api.post("/erp/inventory/nrv/", {}, format="json")

        response = self.api.get("/erp/inventory/nrv/")

        self.assertEqual(response.data["count"], 1)
        self.assertEqual(Decimal(response.data["results"][0]["total_adjustment"]), Decimal("8"))

    def test_ledger_endpoint_filters_by_change_type(self):
        self.receive(3)
        self.deliver(1)

        response = self.api.get("/erp/inventory/ledger/", {
            "change_type": "DELIVERY", "location": str(self.stock_loc.id),
        })

        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["change_type"], "DELIVERY")

    def test_moves_record_when_they_were_done(self):
        self.receive(2)

        move = StockMove.objects.get()
        row = self.api.get("/erp/inventory/move-lines/").data["results"][0]

        self.assertIsNotNone(move.date_done)
        self.assertEqual(parse_datetime(row["date"]), move.date_done)


class ReturnFilterTests(InventoryTestBase):

    def test_returns_are_linked_to_their_original_and_can_be_filtered(self):
        original_id = self.receive(3)

        response = self.api.post(f"/erp/inventory/pickings/{original_id}/return/", {}, format="json")
        self.assertEqual(response.status_code, 201, response.data)

        returns = self.api.get("/erp/inventory/pickings/", {"is_return": "true"})
        self.assertEqual(returns.data["count"], 1)
        self.assertEqual(str(StockPicking.objects.get(pk=response.data["id"]).return_of_id), original_id)

        everything = self.api.get("/erp/inventory/pickings/")
        self.assertEqual(everything.data["count"], 2)


class BackfillCommandTests(InventoryTestBase):

    def test_backfill_creates_opening_entry_and_layer_once(self):
        from django.core.management import call_command
        from inventory_apps.erp_inventory.models import InventoryCostLayer, StockLedgerEntry

        StockQuant.objects.create(product=self.product, location=self.stock_loc, quantity=Decimal("4"))

        call_command("backfill_inventory_layers", verbosity=0)
        call_command("backfill_inventory_layers", verbosity=0)

        self.assertEqual(InventoryCostLayer.objects.filter(location=self.stock_loc).count(), 1)
        self.assertEqual(StockLedgerEntry.objects.filter(change_type="OPENING_BALANCE").count(), 1)
        self.assertEqual(self.on_hand(), Decimal("4"))
