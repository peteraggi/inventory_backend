# inventory_apps/erp_purchase/services.py

"""
PurchaseService: confirm, cancel and bill purchase orders.

Business rules live here so the views stay thin. Failures raise the exceptions in
erp_purchase/exceptions.py, which the API returns as {"success": false, "error": "..."}.
"""
from django.db import transaction
from django.utils import timezone

from inventory_apps.erp_purchase.exceptions import (
    AccountingSetupError, AlreadyBilledError, OrderCancellationError,
    OrderStateError, PurchaseOrderError,
)


from inventory_core.errors import user_message
def _receipts_for(order):
    from inventory_apps.erp_inventory.models import StockPicking
    return StockPicking.objects.filter(origin=order.name)


class PurchaseService:

    @classmethod
    @transaction.atomic
    def confirm_purchase_order(cls, purchase_order):
        """Confirm an RFQ into a purchase order and raise the receipt for its goods."""
        from inventory_apps.erp_inventory.services import StockService

        if purchase_order.state not in ("draft", "sent"):
            raise OrderStateError(f"Cannot confirm PO in state '{purchase_order.state}'")
        if not purchase_order.lines.exists():
            raise PurchaseOrderError("Add at least one line before confirming the order")

        purchase_order.state = "purchase"
        purchase_order.date_approve = timezone.now()
        purchase_order.save(update_fields=["state", "date_approve"])

        try:
            StockService.create_receipt_from_po(purchase_order)
        except ValueError as e:
            raise PurchaseOrderError(user_message(e, "This purchase order could not be updated."))

        purchase_order.receipt_count = _receipts_for(purchase_order).count()
        purchase_order.save(update_fields=["receipt_count"])
        return purchase_order

    @classmethod
    @transaction.atomic
    def cancel_purchase_order(cls, purchase_order):
        """
        Cancel an order and its open receipts. Refused once goods have arrived or the
        order has been billed, because those need a return or a vendor credit note.
        """
        if purchase_order.state == "done":
            raise OrderCancellationError("A locked order cannot be cancelled")
        if purchase_order.state == "cancel":
            return purchase_order
        if _receipts_for(purchase_order).filter(state="done").exists():
            raise OrderCancellationError(
                "Cannot cancel: goods have already been received. Create a return instead."
            )
        if purchase_order.invoice_count > 0:
            raise OrderCancellationError("Cannot cancel a billed order. Cancel the vendor bill first.")

        for picking in _receipts_for(purchase_order).exclude(state__in=("done", "cancel")):
            picking.action_cancel()
        purchase_order.state = "cancel"
        purchase_order.save(update_fields=["state"])
        return purchase_order

    @classmethod
    @transaction.atomic
    def create_bill_from_po(cls, purchase_order):
        """
        Bill the quantity not yet billed on each line. Repeating the action never bills
        the same goods twice.
        """
        from inventory_apps.erp_accounting.models import AccountMove, AccountMoveLine, AccountJournal, AccountAccount

        if purchase_order.state not in ("purchase", "done"):
            raise OrderStateError("Can only bill confirmed purchase orders")

        pending = [
            line for line in purchase_order.lines.all()
            if line.product_qty - line.qty_billed > 0
        ]
        if not pending:
            raise AlreadyBilledError()

        journal = AccountJournal.objects.filter(journal_type="purchase", active=True).first()
        if not journal:
            raise AccountingSetupError("No purchase journal configured.")

        ap_account = AccountAccount.objects.filter(account_type="liability_payable", active=True).first()
        expense_account = AccountAccount.objects.filter(
            account_type="expense_direct_cost", active=True
        ).first() or AccountAccount.objects.filter(account_type="expense", active=True).first()
        line_account = expense_account or ap_account
        if not line_account:
            raise AccountingSetupError(
                "No expense or payable account configured. Please set up your chart of accounts."
            )

        move = AccountMove.objects.create(
            move_type="in_invoice",
            partner=purchase_order.partner,
            journal=journal,
            invoice_origin=purchase_order.name,
            purchase_order=purchase_order,
            currency=purchase_order.currency,
        )
        for line in pending:
            quantity = line.product_qty - line.qty_billed
            move_line = AccountMoveLine.objects.create(
                move=move,
                product=line.product,
                account=line_account,
                name=line.description or line.product.name,
                quantity=quantity,
                price_unit=line.price_unit,
            )
            move_line.taxes.set(line.taxes.all())
            move_line.compute_amount()
            line.qty_billed = line.qty_billed + quantity
            line.save(update_fields=["qty_billed"])

        move.compute_totals()
        purchase_order.invoice_count += 1
        purchase_order.save(update_fields=["invoice_count"])
        return move
