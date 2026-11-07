# inventory_apps/erp_inventory/test_sales_purchase.py
"""
Sales and purchase orders, end to end: permissions, stock hand-off, invoicing and billing.
"""
from decimal import Decimal

from inventory_apps.erp_accounting.models import AccountAccount, AccountJournal, AccountMove
from inventory_apps.erp_base.models import Partner
from inventory_apps.erp_inventory.models import StockLedgerEntry, StockPicking
from inventory_apps.erp_inventory.test_permissions import RoleClientMixin
from inventory_apps.erp_inventory.tests import InventoryTestBase


class OrderTestBase(RoleClientMixin, InventoryTestBase):

    def setUp(self):
        super().setUp()
        self.partner = Partner.objects.create(name="Acme Ltd")
        AccountJournal.objects.create(code="SJ", name="Sales", journal_type="sale")
        AccountJournal.objects.create(code="PJ", name="Purchases", journal_type="purchase")
        AccountAccount.objects.create(code="400000", name="Income", account_type="income")
        AccountAccount.objects.create(code="120000", name="Receivable", account_type="asset_receivable")
        AccountAccount.objects.create(code="500000", name="COGS", account_type="expense_direct_cost")
        AccountAccount.objects.create(code="210000", name="Payable", account_type="liability_payable")

    def sales_order(self, client, qty="4", price="10"):
        response = client.post("/erp/sales/orders/", {
            "partner": str(self.partner.id),
            "lines": [{"product": str(self.product.id), "product_uom_qty": qty, "price_unit": price}],
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["id"]

    def purchase_order(self, client, qty="6", price="5"):
        response = client.post("/erp/purchase/orders/", {
            "partner": str(self.partner.id),
            "lines": [{"product": str(self.product.id), "product_qty": qty, "price_unit": price}],
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["id"]


class SalesFlowTests(OrderTestBase):

    def test_salesperson_creates_and_confirms_and_a_delivery_is_raised(self):
        sales, _ = self.client_for("salesperson")
        order_id = self.sales_order(sales)

        response = sales.post(f"/erp/sales/orders/{order_id}/confirm/", {}, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["state"], "sale")
        self.assertEqual(response.data["delivery_count"], 1)
        delivery = StockPicking.objects.get(origin=response.data["name"])
        self.assertEqual(delivery.picking_type.code, "outgoing")

    def test_confirmed_order_lines_cannot_be_rewritten(self):
        order_id = self.sales_order(self.api)
        self.api.post(f"/erp/sales/orders/{order_id}/confirm/", {}, format="json")

        response = self.api.patch(f"/erp/sales/orders/{order_id}/", {
            "lines": [{"product": str(self.product.id), "product_uom_qty": "99", "price_unit": "1"}],
        }, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("quotation", str(response.data))

    def test_invoice_bills_each_unit_once(self):
        order_id = self.sales_order(self.api, qty="4")
        self.api.post(f"/erp/sales/orders/{order_id}/confirm/", {}, format="json")

        first = self.api.post(f"/erp/sales/orders/{order_id}/create-invoice/", {}, format="json")
        second = self.api.post(f"/erp/sales/orders/{order_id}/create-invoice/", {}, format="json")

        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 400)
        self.assertEqual(second.data["error"], "Everything on this order is already invoiced")
        self.assertEqual(AccountMove.objects.filter(move_type="out_invoice").count(), 1)
        order = self.api.get(f"/erp/sales/orders/{order_id}/").data
        self.assertEqual(order["invoice_count"], 1)

    def test_salesperson_cannot_create_invoices(self):
        sales, _ = self.client_for("salesperson")
        order_id = self.sales_order(sales)
        sales.post(f"/erp/sales/orders/{order_id}/confirm/", {}, format="json")

        response = sales.post(f"/erp/sales/orders/{order_id}/create-invoice/", {}, format="json")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(AccountMove.objects.count(), 0)

    def test_cancel_removes_the_open_delivery(self):
        order_id = self.sales_order(self.api)
        self.api.post(f"/erp/sales/orders/{order_id}/confirm/", {}, format="json")

        response = self.api.post(f"/erp/sales/orders/{order_id}/cancel/", {}, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["state"], "cancel")
        self.assertEqual(StockPicking.objects.get(origin=response.data["name"]).state, "cancel")

    def test_cancel_is_refused_once_goods_have_left(self):
        self.receive(10, price=5)
        order_id = self.sales_order(self.api)
        confirmed = self.api.post(f"/erp/sales/orders/{order_id}/confirm/", {}, format="json")
        delivery = StockPicking.objects.get(origin=confirmed.data["name"])
        self.api.post(f"/erp/inventory/pickings/{delivery.id}/validate/", {}, format="json")

        response = self.api.post(f"/erp/sales/orders/{order_id}/cancel/", {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("already been delivered", response.data["error"])

    def test_validated_delivery_reduces_stock_and_is_ledgered(self):
        self.receive(10, price=5)
        order_id = self.sales_order(self.api, qty="4")
        confirmed = self.api.post(f"/erp/sales/orders/{order_id}/confirm/", {}, format="json")
        delivery = StockPicking.objects.get(origin=confirmed.data["name"])

        self.api.post(f"/erp/inventory/pickings/{delivery.id}/validate/", {}, format="json")

        self.assertEqual(self.on_hand(), Decimal("6"))
        self.assertTrue(StockLedgerEntry.objects.filter(change_type="DELIVERY", reference_name=delivery.name).exists())

    def test_delivery_cannot_take_more_than_is_on_hand(self):
        self.receive(3, price=5)
        order_id = self.sales_order(self.api, qty="4")
        confirmed = self.api.post(f"/erp/sales/orders/{order_id}/confirm/", {}, format="json")
        delivery = StockPicking.objects.get(origin=confirmed.data["name"])

        response = self.api.post(f"/erp/inventory/pickings/{delivery.id}/validate/", {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("Not enough stock", response.data["error"])
        self.assertEqual(self.on_hand(), Decimal("3"))
        self.assertEqual(StockPicking.objects.get(pk=delivery.id).state, "confirmed")

    def test_invalid_line_values_are_rejected(self):
        response = self.api.post("/erp/sales/orders/", {
            "partner": str(self.partner.id),
            "lines": [{"product": str(self.product.id), "product_uom_qty": "0", "price_unit": "-3", "discount": "150"}],
        }, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data["success"])
        self.assertIn("lines", response.data["details"])
        self.assertIn("Quantity must be greater than zero", response.data["error"])

    def test_purchasing_role_has_no_access_to_sales(self):
        purchasing, _ = self.client_for("purchasing")

        self.assertEqual(purchasing.get("/erp/sales/orders/").status_code, 403)


class PurchaseFlowTests(OrderTestBase):

    def test_confirm_raises_a_receipt_and_receiving_adds_stock(self):
        order_id = self.purchase_order(self.api, qty="6", price="5")

        confirmed = self.api.post(f"/erp/purchase/orders/{order_id}/confirm/", {}, format="json")

        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assertEqual(confirmed.data["receipt_count"], 1)
        receipt = StockPicking.objects.get(origin=confirmed.data["name"])
        self.api.post(f"/erp/inventory/pickings/{receipt.id}/validate/", {}, format="json")
        self.assertEqual(self.on_hand(), Decimal("6"))

    def test_purchasing_role_can_confirm_but_not_bill(self):
        purchasing, _ = self.client_for("purchasing")
        order_id = self.purchase_order(purchasing)

        confirmed = purchasing.post(f"/erp/purchase/orders/{order_id}/confirm/", {}, format="json")
        bill = purchasing.post(f"/erp/purchase/orders/{order_id}/create-bill/", {}, format="json")

        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assertEqual(bill.status_code, 403)

    def test_bill_covers_each_unit_once(self):
        order_id = self.purchase_order(self.api)
        self.api.post(f"/erp/purchase/orders/{order_id}/confirm/", {}, format="json")

        first = self.api.post(f"/erp/purchase/orders/{order_id}/create-bill/", {}, format="json")
        second = self.api.post(f"/erp/purchase/orders/{order_id}/create-bill/", {}, format="json")

        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 400)
        self.assertEqual(second.data["error"], "Everything on this order is already billed")
        self.assertEqual(AccountMove.objects.filter(move_type="in_invoice").count(), 1)

    def test_cancel_is_refused_once_goods_are_received(self):
        order_id = self.purchase_order(self.api)
        confirmed = self.api.post(f"/erp/purchase/orders/{order_id}/confirm/", {}, format="json")
        receipt = StockPicking.objects.get(origin=confirmed.data["name"])
        self.api.post(f"/erp/inventory/pickings/{receipt.id}/validate/", {}, format="json")

        response = self.api.post(f"/erp/purchase/orders/{order_id}/cancel/", {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("already been received", response.data["error"])

    def test_cancel_before_receiving_removes_the_receipt(self):
        order_id = self.purchase_order(self.api)
        confirmed = self.api.post(f"/erp/purchase/orders/{order_id}/confirm/", {}, format="json")

        response = self.api.post(f"/erp/purchase/orders/{order_id}/cancel/", {}, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(StockPicking.objects.get(origin=confirmed.data["name"]).state, "cancel")

    def test_salesperson_has_no_access_to_purchasing(self):
        sales, _ = self.client_for("salesperson")

        self.assertEqual(sales.get("/erp/purchase/orders/").status_code, 403)

    def test_non_positive_quantity_rejected(self):
        response = self.api.post("/erp/purchase/orders/", {
            "partner": str(self.partner.id),
            "lines": [{"product": str(self.product.id), "product_qty": "-1", "price_unit": "5"}],
        }, format="json")

        self.assertEqual(response.status_code, 400)


class QuotationSalespersonTests(OrderTestBase):

    def test_quotation_records_and_shows_the_salesperson_who_created_it(self):
        sales, user = self.client_for("salesperson", email="quote-maker@test.local")
        order_id = self.sales_order(sales)

        detail = sales.get(f"/erp/sales/orders/{order_id}/")
        listed = sales.get("/erp/sales/orders/")

        self.assertEqual(str(detail.data["salesperson"]), str(user.pk))
        self.assertEqual(detail.data["salesperson_name"], user.name)
        row = next(r for r in listed.data["results"] if r["id"] == order_id)
        self.assertEqual(row["salesperson_name"], user.name)


class TermsAndConditionsTests(OrderTestBase):
    """Terms stay editable while a quotation or RFQ is open, and are locked once it is confirmed."""

    def test_quotation_terms_can_be_edited(self):
        order_id = self.sales_order(self.api)

        response = self.api.patch(f"/erp/sales/orders/{order_id}/", {"note": "Payment within 14 days."}, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["note"], "Payment within 14 days.")

    def test_confirmed_sales_order_terms_are_locked(self):
        order_id = self.sales_order(self.api)
        self.api.post(f"/erp/sales/orders/{order_id}/confirm/", {}, format="json")

        response = self.api.patch(f"/erp/sales/orders/{order_id}/", {"note": "Changed later"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("Terms can only be changed", str(response.data))

    def test_rfq_terms_can_be_edited_until_confirmed(self):
        order_id = self.purchase_order(self.api)

        response = self.api.patch(f"/erp/purchase/orders/{order_id}/", {"notes": "Delivery to head office."}, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["notes"], "Delivery to head office.")
