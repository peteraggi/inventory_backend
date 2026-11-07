# inventory_apps/erp_inventory/test_costing.py
from decimal import Decimal

from django.db import IntegrityError, transaction

from inventory_apps.erp_base.models import ProductTemplate
from inventory_apps.erp_inventory.models import InventoryCostLayer, StockLedgerEntry, StockLot, StockMove, StockPicking, StockQuant
from inventory_apps.erp_inventory.tests import InventoryTestBase


class LotCostingTests(InventoryTestBase):

    def setUp(self):
        super().setUp()
        self.lot_a = StockLot.objects.create(name="LOT-A", product=self.product)
        self.lot_b = StockLot.objects.create(name="LOT-B", product=self.product)

    def receive_lot(self, lot, qty, price):
        response = self.api.post("/erp/inventory/pickings/", {
            "picking_type": str(self.receipt_type.id),
            "location_src": str(self.vendor_loc.id),
            "location_dest": str(self.stock_loc.id),
            "move_lines": [{
                "product": str(self.product.id), "lot": str(lot.id),
                "product_uom_qty": str(qty), "price_unit": str(price),
            }],
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.api.post(f"/erp/inventory/pickings/{response.data['id']}/confirm/", {}, format="json")
        response = self.api.post(f"/erp/inventory/pickings/{response.data['id']}/validate/", {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)

    def test_each_lot_is_costed_and_consumed_separately(self):
        self.receive_lot(self.lot_a, 10, 5)
        self.receive_lot(self.lot_b, 10, 8)

        delivery_type = self.warehouse.picking_types.get(code="outgoing")
        response = self.api.post("/erp/inventory/pickings/", {
            "picking_type": str(delivery_type.id),
            "location_src": str(self.stock_loc.id),
            "location_dest": str(delivery_type.default_location_dest.id),
            "move_lines": [{"product": str(self.product.id), "lot": str(self.lot_a.id), "product_uom_qty": "4"}],
        }, format="json")
        self.api.post(f"/erp/inventory/pickings/{response.data['id']}/confirm/", {}, format="json")
        validated = self.api.post(f"/erp/inventory/pickings/{response.data['id']}/validate/", {}, format="json")
        self.assertEqual(validated.status_code, 200, validated.data)

        # Lot A gave up 4 at 5; lot B is untouched at 8.
        self.assertEqual(InventoryCostLayer.objects.get(lot=self.lot_a).quantity_remaining, Decimal("6"))
        self.assertEqual(InventoryCostLayer.objects.get(lot=self.lot_b).quantity_remaining, Decimal("10"))

        rows = {r["lot_name"]: r for r in self.api.get("/erp/inventory/valuation/").data["results"]}
        self.assertEqual(Decimal(rows["LOT-A"]["value"]), Decimal("30"))
        self.assertEqual(Decimal(rows["LOT-B"]["value"]), Decimal("80"))

    def test_nrv_applies_per_lot(self):
        ProductTemplate.objects.filter(pk=self.product.product_template_id).update(sale_price=Decimal("6"))
        self.receive_lot(self.lot_a, 2, 8)
        self.receive_lot(self.lot_b, 2, 4)

        response = self.api.post("/erp/inventory/nrv/", {}, format="json")

        # Only lot A's cost (8) is above the sale price (6).
        self.assertEqual(response.data["created"], 1)
        self.assertEqual(InventoryCostLayer.objects.get(lot=self.lot_a).unit_cost, Decimal("6"))
        self.assertEqual(InventoryCostLayer.objects.get(lot=self.lot_b).unit_cost, Decimal("4"))


class LedgerUniquenessTests(InventoryTestBase):

    def test_transfer_with_two_lines_for_the_same_product_posts_cleanly(self):
        response = self.api.post("/erp/inventory/pickings/", {
            "picking_type": str(self.receipt_type.id),
            "location_src": str(self.vendor_loc.id),
            "location_dest": str(self.stock_loc.id),
            "move_lines": [
                {"product": str(self.product.id), "product_uom_qty": "2"},
                {"product": str(self.product.id), "product_uom_qty": "3"},
            ],
        }, format="json")
        self.api.post(f"/erp/inventory/pickings/{response.data['id']}/confirm/", {}, format="json")

        validated = self.api.post(f"/erp/inventory/pickings/{response.data['id']}/validate/", {}, format="json")

        self.assertEqual(validated.status_code, 200, validated.data)
        self.assertEqual(self.on_hand(), Decimal("5"))
        self.assertEqual(StockLedgerEntry.objects.filter(change_type="RECEIPT", location=self.stock_loc).count(), 2)

    def test_one_move_cannot_post_twice_to_the_same_location(self):
        picking = StockPicking.objects.create(
            picking_type=self.receipt_type, location_src=self.vendor_loc, location_dest=self.stock_loc,
        )
        move = StockMove.objects.create(
            picking=picking, product=self.product, product_uom_qty=Decimal("1"),
            location_src=self.vendor_loc, location_dest=self.stock_loc,
        )
        base = {"product": self.product, "location": self.stock_loc, "change_type": "RECEIPT",
                "quantity_change": Decimal("1"), "resulting_quantity": Decimal("1"),
                "source_move": move}
        StockLedgerEntry.objects.create(**base)

        with self.assertRaises(IntegrityError), transaction.atomic():
            StockLedgerEntry.objects.create(**base)

    def test_layer_lot_is_optional(self):
        layer = InventoryCostLayer.objects.create(
            product=self.product, location=self.stock_loc, quantity_received=Decimal("1"),
            quantity_remaining=Decimal("1"), unit_cost=Decimal("2"),
        )
        self.assertIsNone(layer.lot)


class BackfillDryRunTests(InventoryTestBase):

    def test_dry_run_reports_without_writing(self):
        from io import StringIO
        from django.core.management import call_command
        from inventory_apps.erp_inventory.models import InventoryCostLayer, StockLedgerEntry

        StockQuant.objects.create(product=self.product, location=self.stock_loc, quantity=Decimal("4"))
        out = StringIO()

        call_command("backfill_inventory_layers", "--dry-run", stdout=out, verbosity=0)

        self.assertIn("Would create opening balances: 1", out.getvalue())
        self.assertEqual(InventoryCostLayer.objects.count(), 0)
        self.assertEqual(StockLedgerEntry.objects.filter(change_type="OPENING_BALANCE").count(), 0)
