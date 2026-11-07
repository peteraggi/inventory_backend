# inventory_apps/erp_inventory/test_accounting.py
from decimal import Decimal

from django.db.models import Sum

from inventory_apps.erp_base.models import ProductTemplate
from inventory_apps.erp_accounting.models import AccountMove, AccountMoveLine
from inventory_apps.erp_inventory.accounting import ACCOUNT_SPECS
from inventory_apps.erp_inventory.models import StockQuant
from inventory_apps.erp_inventory.tests import InventoryTestBase


class GeneralLedgerTests(InventoryTestBase):

    def set_prices(self, sale=None, standard=None):
        update = {}
        if sale is not None:
            update["sale_price"] = Decimal(sale)
        if standard is not None:
            update["standard_price"] = Decimal(standard)
        ProductTemplate.objects.filter(pk=self.product.product_template_id).update(**update)

    def balance(self, key):
        code = ACCOUNT_SPECS[key][0]
        totals = AccountMoveLine.objects.filter(
            account__code=code, move__state="posted",
        ).aggregate(debit=Sum("debit"), credit=Sum("credit"))
        return (totals["debit"] or Decimal("0")) - (totals["credit"] or Decimal("0"))

    def inventory_value(self):
        response = self.api.get("/erp/inventory/valuation/")
        return Decimal(response.data["total_value"])

    def assert_ledger_matches_stock(self):
        self.assertEqual(self.balance("inventory"), self.inventory_value())

    def deliver(self, qty):
        delivery_type = self.warehouse.picking_types.get(code="outgoing")
        response = self.api.post("/erp/inventory/pickings/", {
            "picking_type": str(delivery_type.id),
            "location_src": str(self.stock_loc.id),
            "location_dest": str(delivery_type.default_location_dest.id),
            "move_lines": [{"product": str(self.product.id), "product_uom_qty": str(qty)}],
        }, format="json")
        self.api.post(f"/erp/inventory/pickings/{response.data['id']}/confirm/", {}, format="json")
        validated = self.api.post(f"/erp/inventory/pickings/{response.data['id']}/validate/", {}, format="json")
        self.assertEqual(validated.status_code, 200, validated.data)

    def test_receipt_debits_inventory_and_credits_goods_not_invoiced(self):
        self.receive(10, price=5)

        self.assertEqual(self.balance("inventory"), Decimal("50"))
        self.assertEqual(self.balance("stock_input"), Decimal("-50"))
        self.assert_ledger_matches_stock()

    def test_delivery_moves_cost_to_cost_of_goods_sold(self):
        self.receive(10, price=5)

        self.deliver(4)

        self.assertEqual(self.balance("cogs"), Decimal("20"))
        self.assertEqual(self.balance("inventory"), Decimal("30"))
        self.assert_ledger_matches_stock()

    def test_internal_transfer_posts_nothing(self):
        self.receive(6, price=2)
        entries_before = AccountMove.objects.count()
        internal_type = self.warehouse.picking_types.get(code="internal")
        response = self.api.post("/erp/inventory/pickings/", {
            "picking_type": str(internal_type.id),
            "location_src": str(self.stock_loc.id),
            "location_dest": str(self.stock_loc.id),
            "move_lines": [{"product": str(self.product.id), "product_uom_qty": "2"}],
        }, format="json")
        self.api.post(f"/erp/inventory/pickings/{response.data['id']}/confirm/", {}, format="json")
        self.api.post(f"/erp/inventory/pickings/{response.data['id']}/validate/", {}, format="json")

        self.assertEqual(AccountMove.objects.count(), entries_before)
        self.assert_ledger_matches_stock()

    def test_physical_count_gain_and_loss_post_to_adjustments(self):
        self.set_prices(standard="5")
        self.receive(10, price=5)
        quant = StockQuant.objects.get(product=self.product, location=self.stock_loc)

        response = self.api.post("/erp/inventory/quants/apply/", {
            "quants": [{"quant_id": str(quant.id), "inventory_quantity": "12"}],
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.balance("inventory"), Decimal("60"))

        self.api.post("/erp/inventory/quants/apply/", {
            "quants": [{"quant_id": str(quant.id), "inventory_quantity": "11"}],
        }, format="json")
        self.assertEqual(self.balance("inventory"), Decimal("55"))
        self.assertEqual(self.balance("adjustments"), Decimal("-5"))
        self.assert_ledger_matches_stock()

    def test_scrap_writes_value_off_through_adjustments(self):
        self.receive(10, price=4)
        scrap = self.api.post("/erp/inventory/scrap/", {"product": str(self.product.id), "quantity": 3}, format="json")

        response = self.api.post(f"/erp/inventory/scrap/{scrap.data['id']}/validate/", {}, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.balance("adjustments"), Decimal("12"))
        self.assertEqual(self.balance("inventory"), Decimal("28"))
        self.assert_ledger_matches_stock()

    def test_nrv_write_down_posts_and_matches_stock(self):
        self.set_prices(sale="6")
        self.receive(5, price=8)

        self.api.post("/erp/inventory/nrv/", {}, format="json")

        self.assertEqual(self.balance("write_down"), Decimal("10"))
        self.assertEqual(self.balance("inventory"), Decimal("30"))
        self.assert_ledger_matches_stock()

    def test_every_posted_entry_balances(self):
        self.set_prices(standard="5", sale="6")
        self.receive(10, price=5)
        self.deliver(3)
        self.api.post("/erp/inventory/nrv/", {}, format="json")

        for move in AccountMove.objects.filter(state="posted"):
            totals = move.lines.aggregate(debit=Sum("debit"), credit=Sum("credit"))
            self.assertEqual(totals["debit"], totals["credit"], move.name)
