# inventory_apps/erp_accounting/tests.py
from decimal import Decimal

from inventory_apps.erp_accounting.models import AccountAccount, AccountJournal, AccountMove, AccountMoveLine, AccountPayment
from inventory_apps.erp_base.models import Partner
from inventory_apps.erp_inventory.tests import InventoryTestBase


class AccountingTestBase(InventoryTestBase):

    def setUp(self):
        super().setUp()
        self.partner = Partner.objects.create(name="Acme Ltd")
        self.sales_journal = AccountJournal.objects.create(code="SJ", name="Sales", journal_type="sale")
        self.income = AccountAccount.objects.create(code="400000", name="Income", account_type="income")
        self.receivable = AccountAccount.objects.create(code="120000", name="Receivable", account_type="asset_receivable")
        self.bank = AccountAccount.objects.create(code="100100", name="Bank", account_type="asset_cash")
        self.cash_journal = AccountJournal.objects.create(
            code="BK", name="Bank", journal_type="bank", default_account=self.bank,
        )

    def draft_invoice(self, price="100", qty="1"):
        move = AccountMove.objects.create(
            move_type="out_invoice", partner=self.partner, journal=self.sales_journal,
        )
        line = AccountMoveLine.objects.create(
            move=move, account=self.income, name="Consulting",
            quantity=Decimal(qty), price_unit=Decimal(price),
        )
        line.compute_amount()
        move.compute_totals()
        return move

    def post(self, move):
        return self.api.post(f"/erp/accounting/moves/{move.id}/post/", {}, format="json")


class PostingTests(AccountingTestBase):

    def test_invoice_posts_when_receivable_account_exists(self):
        move = self.draft_invoice(price="100")
        self.receivable_counterpart_ready = True

        response = self.post(move)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["state"], "posted")
        self.assertTrue(response.data["name"].startswith("INV"))

    def test_invoice_is_refused_when_no_receivable_account_exists(self):
        self.receivable.delete()
        move = self.draft_invoice()

        response = self.post(move)

        self.assertEqual(response.status_code, 400)
        self.assertIn("No receivable account", response.data["error"])
        move.refresh_from_db()
        self.assertEqual(move.state, "draft")

    def test_empty_document_cannot_be_posted(self):
        move = AccountMove.objects.create(move_type="out_invoice", partner=self.partner, journal=self.sales_journal)

        response = self.post(move)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"], "Add at least one line before posting.")

    def test_unbalanced_journal_entry_is_refused(self):
        move = AccountMove.objects.create(move_type="entry", journal=self.sales_journal)
        AccountMoveLine.objects.create(move=move, account=self.bank, name="x", debit=Decimal("10"))
        AccountMoveLine.objects.create(move=move, account=self.income, name="y", credit=Decimal("7"))

        response = self.post(move)

        self.assertEqual(response.status_code, 400)
        self.assertIn("does not balance", response.data["error"])

    def test_posted_documents_cannot_be_edited_or_deleted(self):
        move = self.draft_invoice()
        self.post(move)

        edited = self.api.patch(f"/erp/accounting/moves/{move.id}/", {"narration": "changed"}, format="json")
        deleted = self.api.delete(f"/erp/accounting/moves/{move.id}/")

        self.assertEqual(edited.status_code, 400)
        self.assertEqual(deleted.status_code, 400)
        self.assertIn("cannot be changed", edited.data["error"])

    def test_trial_balance_includes_posted_invoice_lines(self):
        self.post(self.draft_invoice(price="250"))

        response = self.api.get("/erp/accounting/reports/trial-balance/", {"date_from": "2000-01-01"})

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(Decimal(str(response.data["total_credit"])), Decimal("250"))
        self.assertEqual(response.data["total_debit"], response.data["total_credit"])


class PaymentTests(AccountingTestBase):

    def posted_invoice(self, price="100"):
        move = self.draft_invoice(price=price)
        self.post(move)
        move.refresh_from_db()
        return move

    def pay(self, move, amount):
        return self.api.post(f"/erp/accounting/moves/{move.id}/register-payment/", {
            "journal": str(self.cash_journal.id), "amount": str(amount),
        }, format="json")

    def test_partial_then_full_payment_settles_the_invoice(self):
        move = self.posted_invoice("100")

        self.assertEqual(self.pay(move, 40).status_code, 201)
        self.assertEqual(self.pay(move, 60).status_code, 201)

        move.refresh_from_db()
        self.assertEqual(move.payment_state, "paid")
        self.assertEqual(move.amount_residual, Decimal("0"))

    def test_overpayment_is_refused(self):
        move = self.posted_invoice("100")

        response = self.pay(move, 150)

        self.assertEqual(response.status_code, 400)
        self.assertIn("more than the 100", response.data["error"])
        self.assertEqual(AccountPayment.objects.count(), 0)

    def test_zero_or_negative_payment_is_refused(self):
        move = self.posted_invoice("100")

        self.assertEqual(self.pay(move, 0).status_code, 400)
        self.assertEqual(self.pay(move, -5).status_code, 400)

    def test_payment_without_accounts_is_refused_not_silently_recorded(self):
        move = self.posted_invoice("100")
        self.bank.delete()

        response = self.api.post(f"/erp/accounting/moves/{move.id}/register-payment/", {
            "journal": str(self.cash_journal.id), "amount": "10",
        }, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(AccountPayment.objects.count(), 0)
        move.refresh_from_db()
        self.assertEqual(move.amount_paid, Decimal("0"))

    def test_posted_payment_cannot_be_edited(self):
        move = self.posted_invoice("100")
        payment_id = self.pay(move, 30).data["id"]  # registered payments are reconciled, not draft

        response = self.api.patch(f"/erp/accounting/payments/{payment_id}/", {"amount": "999"}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(AccountPayment.objects.get(pk=payment_id).amount, Decimal("30"))
