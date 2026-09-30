"""
erp_purchase/services.py — PurchaseService: confirm PO, receive goods, create vendor bill.
"""
from decimal import Decimal
from django.db import transaction


class PurchaseService:

    @classmethod
    @transaction.atomic
    def confirm_purchase_order(cls, purchase_order):
        from inventory_apps.erp_inventory.services import StockService
        if purchase_order.state not in ("draft", "sent"):
            raise ValueError(f"Cannot confirm PO in state '{purchase_order.state}'")

        purchase_order.state = "purchase"
        from django.utils import timezone
        purchase_order.date_approve = timezone.now()
        purchase_order.save(update_fields=["state", "date_approve"])

        # Create incoming picking (receipt)
        picking = StockService.create_receipt_from_po(purchase_order)
        return purchase_order

    @classmethod
    @transaction.atomic
    def create_bill_from_po(cls, purchase_order):
        from inventory_apps.erp_accounting.models import AccountMove, AccountMoveLine, AccountJournal
        if purchase_order.state not in ("purchase", "done"):
            raise ValueError("Can only bill confirmed purchase orders")

        journal = AccountJournal.objects.filter(journal_type="purchase", active=True).first()
        if not journal:
            raise ValueError("No purchase journal configured.")

        move = AccountMove.objects.create(
            move_type="in_invoice",
            partner=purchase_order.partner,
            journal=journal,
            invoice_origin=purchase_order.name,
            purchase_order=purchase_order,
            currency=purchase_order.currency,
        )
        from inventory_apps.erp_accounting.models import AccountAccount
        ap_account = AccountAccount.objects.filter(
            account_type="liability_payable", active=True
        ).first()
        expense_account = AccountAccount.objects.filter(
            account_type="expense_direct_cost", active=True
        ).first() or AccountAccount.objects.filter(account_type="expense", active=True).first()
        line_account = expense_account or ap_account
        if not line_account:
            raise ValueError(
                "No expense or payable account configured. Please set up your chart of accounts."
            )

        for line in purchase_order.lines.all():
            move_line = AccountMoveLine.objects.create(
                move=move,
                product=line.product,
                account=line_account,
                name=line.description or line.product.name,
                quantity=line.product_qty,
                price_unit=line.price_unit,
            )
            move_line.taxes.set(line.taxes.all())
            move_line.compute_amount()
            line.qty_billed = line.product_qty
            line.save(update_fields=["qty_billed"])

        move.compute_totals()
        purchase_order.invoice_count += 1
        purchase_order.save(update_fields=["invoice_count"])
        return move
