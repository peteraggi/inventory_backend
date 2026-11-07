# inventory_apps/erp_pos/tests.py
from decimal import Decimal

from inventory_apps.erp_accounting.models import AccountAccount, AccountJournal, AccountMove, AccountMoveLine
from inventory_apps.erp_inventory.tests import InventoryTestBase
from inventory_apps.erp_pos.models import POSConfig, POSOrder, POSPaymentMethod, POSSession


class POSTestBase(InventoryTestBase):

    def setUp(self):
        super().setUp()
        self.sales_journal = AccountJournal.objects.create(code="SJ", name="Sales", journal_type="sale")
        AccountAccount.objects.create(code="100000", name="Cash", account_type="asset_cash")
        AccountAccount.objects.create(code="400000", name="Income", account_type="income")
        AccountAccount.objects.create(code="220000", name="Sales tax", account_type="liability_current", is_tax_account=True)
        self.cash = POSPaymentMethod.objects.create(name="Cash", is_cash=True)
        self.config = POSConfig.objects.create(name="Front Counter", journal=self.sales_journal)
        self.config.payment_methods.add(self.cash)

    def open_register(self, opening="0"):
        response = self.api.post(f"/erp/pos/configs/{self.config.id}/open-session/",
                                 {"opening_balance": opening}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["id"]

    def sale(self, session_id, qty="2", price="10", paid=None, method=None, external_ref=None):
        """Create a draft sale; `paid` defaults to exactly the total."""
        total = Decimal(qty) * Decimal(price)
        payload = {
            "session": session_id,
            "lines": [{"product": str(self.product.id), "qty": qty, "price_unit": price}],
            "payments": [{"payment_method": str(method.id if method else self.cash.id),
                          "amount": str(paid if paid is not None else total)}],
        }
        if external_ref:
            payload["external_ref"] = external_ref
        response = self.api.post("/erp/pos/orders/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["id"]

    def ledger_balance(self, code):
        from django.db.models import Sum
        totals = AccountMoveLine.objects.filter(account__code=code, move__state="posted").aggregate(
            d=Sum("debit"), c=Sum("credit"))
        return (totals["d"] or Decimal("0")) - (totals["c"] or Decimal("0"))


class PaymentTests(POSTestBase):

    def test_paying_a_sale_reduces_stock_and_posts_to_the_ledger(self):
        self.receive(10, price=5)
        session_id = self.open_register()
        order_id = self.sale(session_id, qty="2", price="10")

        response = self.api.post(f"/erp/pos/orders/{order_id}/pay/", {}, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["state"], "paid")
        self.assertEqual(self.on_hand(), Decimal("8"))
        self.assertEqual(self.ledger_balance("100000"), Decimal("20"))
        self.assertEqual(self.ledger_balance("400000"), Decimal("-20"))
        entry = AccountMove.objects.get(ref=response.data["name"])
        self.assertEqual(entry.state, "posted")

    def test_tax_is_posted_to_the_tax_account_and_entry_balances(self):
        from inventory_apps.erp_base.models import Tax
        self.receive(10, price=5)
        tax = Tax.objects.create(name="VAT 10", amount=Decimal("10"), amount_type="percent", type_tax_use="sale")
        self.product.taxes.add(tax)
        session_id = self.open_register()
        order_id = self.sale(session_id, qty="1", price="100", paid="200")  # overpaid: the rest is change
        response = self.api.post(f"/erp/pos/orders/{order_id}/pay/", {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)

        amount_tax = Decimal(response.data["amount_tax"])
        self.assertEqual(self.ledger_balance("220000") * -1, amount_tax)
        self.assertEqual(self.ledger_balance("100000"), Decimal(response.data["amount_total"]))

    def test_stock_shortage_refuses_the_sale_and_keeps_it_as_a_draft(self):
        self.receive(1, price=5)
        session_id = self.open_register()
        order_id = self.sale(session_id, qty="5", price="10")

        response = self.api.post(f"/erp/pos/orders/{order_id}/pay/", {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data["success"])
        self.assertIn("Not enough stock", response.data["error"])
        self.assertEqual(POSOrder.objects.get(pk=order_id).state, "draft")
        self.assertEqual(self.on_hand(), Decimal("1"))
        self.assertEqual(self.ledger_balance("100000"), Decimal("0"))

    def test_missing_accounts_refuse_payment_and_roll_back_stock(self):
        AccountAccount.objects.filter(account_type="asset_cash").delete()
        self.receive(10, price=5)
        session_id = self.open_register()
        order_id = self.sale(session_id, qty="2", price="10")

        response = self.api.post(f"/erp/pos/orders/{order_id}/pay/", {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("no cash account exists", response.data["error"])
        self.assertEqual(POSOrder.objects.get(pk=order_id).state, "draft")
        self.assertEqual(self.on_hand(), Decimal("10"))

    def test_insufficient_payment_is_refused(self):
        self.receive(10, price=5)
        session_id = self.open_register()
        order_id = self.sale(session_id, qty="2", price="10", paid="5")

        response = self.api.post(f"/erp/pos/orders/{order_id}/pay/", {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("Insufficient payment", response.data["error"])

    def test_payment_method_not_on_the_register_is_refused(self):
        other = POSPaymentMethod.objects.create(name="Voucher")
        session_id = self.open_register()
        response = self.api.post("/erp/pos/orders/", {
            "session": session_id,
            "lines": [{"product": str(self.product.id), "qty": "1", "price_unit": "10"}],
            "payments": [{"payment_method": str(other.id), "amount": "10"}],
        }, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("not accepted", str(response.data))

    def test_line_values_are_validated(self):
        session_id = self.open_register()
        response = self.api.post("/erp/pos/orders/", {
            "session": session_id,
            "lines": [{"product": str(self.product.id), "qty": "0", "price_unit": "-1", "discount": "120"}],
        }, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data["success"])
        self.assertIn("lines", response.data["details"])

    def test_price_defaults_to_the_product_sale_price(self):
        from inventory_apps.erp_base.models import ProductTemplate
        ProductTemplate.objects.filter(pk=self.product.product_template_id).update(sale_price=Decimal("7"))
        session_id = self.open_register()
        response = self.api.post("/erp/pos/orders/", {
            "session": session_id,
            "lines": [{"product": str(self.product.id), "qty": "2"}],
        }, format="json")

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Decimal(response.data["lines"][0]["price_unit"]), Decimal("7"))


class SessionTests(POSTestBase):

    def test_a_register_has_only_one_open_session(self):
        self.open_register()

        second = self.api.post(f"/erp/pos/configs/{self.config.id}/open-session/", {}, format="json")

        self.assertEqual(second.status_code, 400)
        self.assertEqual(second.data["error"], "There is already an open session for this POS.")

    def test_close_is_refused_while_a_draft_sale_is_open(self):
        session_id = self.open_register()
        self.sale(session_id)

        response = self.api.post(f"/erp/pos/sessions/{session_id}/close/", {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("unpaid orders", response.data["error"])

    def test_close_succeeds_once_all_sales_are_paid(self):
        self.receive(10, price=5)
        session_id = self.open_register()
        order_id = self.sale(session_id)
        self.api.post(f"/erp/pos/orders/{order_id}/pay/", {}, format="json")

        response = self.api.post(f"/erp/pos/sessions/{session_id}/close/", {"closing_balance": "20"}, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["state"], "closed")

    def test_session_records_cannot_be_edited_directly(self):
        session_id = self.open_register()

        response = self.api.patch(f"/erp/pos/sessions/{session_id}/", {"state": "closed"}, format="json")

        self.assertEqual(response.status_code, 405)
        self.assertEqual(POSSession.objects.get(pk=session_id).state, "opened")

    def test_sales_need_an_open_session(self):
        session_id = self.open_register()
        self.api.post(f"/erp/pos/sessions/{session_id}/close/", {}, format="json")

        response = self.api.post("/erp/pos/orders/", {
            "session": session_id,
            "lines": [{"product": str(self.product.id), "qty": "1", "price_unit": "1"}],
        }, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("open session", str(response.data))


class OfflineSyncTests(POSTestBase):

    def sale_payload(self, ref, price="10", product=None, method=None):
        return {
            "external_ref": ref,
            "lines": [{"product_id": str(product.id if product else self.product.id), "qty": 1, "price_unit": price}],
            "payments": [{"method_id": str(method.id if method else self.cash.id), "amount": price}],
        }

    def test_good_sales_sync_and_a_bad_one_is_reported_without_blocking_the_rest(self):
        self.receive(10, price=5)
        session_id = self.open_register()
        orders = [
            self.sale_payload("OFF-1"),
            {  # refers to a product that does not exist
                "external_ref": "OFF-2",
                "lines": [{"product_id": "00000000-0000-0000-0000-000000000000", "qty": 1}],
                "payments": [{"method_id": str(self.cash.id), "amount": "10"}],
            },
            self.sale_payload("OFF-3"),
        ]

        response = self.api.post(f"/erp/pos/sessions/{session_id}/sync-offline/", {"orders": orders}, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["synced"], 2)
        self.assertEqual([f["external_ref"] for f in response.data["failed"]], ["OFF-2"])
        self.assertEqual(POSOrder.objects.filter(session_id=session_id, state="paid").count(), 2)
        self.assertEqual(self.on_hand(), Decimal("8"))

    def test_resending_a_synced_sale_skips_it(self):
        self.receive(10, price=5)
        session_id = self.open_register()
        orders = [self.sale_payload("OFF-9")]
        self.api.post(f"/erp/pos/sessions/{session_id}/sync-offline/", {"orders": orders}, format="json")

        again = self.api.post(f"/erp/pos/sessions/{session_id}/sync-offline/", {"orders": orders}, format="json")

        self.assertEqual(again.data["synced"], 0)
        self.assertEqual(again.data["skipped"], ["OFF-9"])
        self.assertEqual(POSOrder.objects.filter(session_id=session_id).count(), 1)
        self.assertEqual(self.on_hand(), Decimal("9"))


class PaidOrderLockTests(POSTestBase):

    def test_paid_orders_cannot_be_changed_or_deleted(self):
        self.receive(10, price=5)
        session_id = self.open_register()
        order_id = self.sale(session_id)
        self.api.post(f"/erp/pos/orders/{order_id}/pay/", {}, format="json")

        changed = self.api.patch(f"/erp/pos/orders/{order_id}/", {
            "lines": [{"product": str(self.product.id), "qty": "99", "price_unit": "1"}],
        }, format="json")
        deleted = self.api.delete(f"/erp/pos/orders/{order_id}/")

        self.assertEqual(changed.status_code, 400)
        self.assertEqual(deleted.status_code, 400)
        self.assertEqual(POSOrder.objects.get(pk=order_id).state, "paid")

    def test_paid_orders_cannot_be_cancelled(self):
        self.receive(10, price=5)
        session_id = self.open_register()
        order_id = self.sale(session_id)
        self.api.post(f"/erp/pos/orders/{order_id}/pay/", {}, format="json")

        response = self.api.post(f"/erp/pos/orders/{order_id}/cancel/", {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"], "Cannot cancel a paid order.")
