# inventory_apps/erp_sales/services.py

"""
SalesService: confirm, cancel and invoice sale orders.

Business rules live here so the views stay thin. Failures raise the exceptions in
erp_sales/exceptions.py, which the API returns as {"success": false, "error": "..."}.
"""
from django.db import transaction

from inventory_apps.erp_sales.exceptions import (
    AccountingSetupError, AlreadyInvoicedError, OrderCancellationError,
    OrderStateError, SalesOrderError,
)


def _pickings_for(order):
    from inventory_apps.erp_inventory.models import StockPicking
    return StockPicking.objects.filter(origin=order.name)


class SalesService:

    @classmethod
    @transaction.atomic
    def confirm_sale_order(cls, sale_order):
        """Confirm a quotation and raise a delivery when it holds storable products."""
        from inventory_apps.erp_inventory.services import StockService

        if sale_order.state not in ("draft", "sent"):
            raise OrderStateError(f"Cannot confirm order in state '{sale_order.state}'")
        if not sale_order.lines.exists():
            raise SalesOrderError("Add at least one line before confirming the order")

        sale_order.state = "sale"
        sale_order.save(update_fields=["state"])

        if any(l.product.product_type == "storable" for l in sale_order.lines.all()):
            try:
                StockService.create_delivery_from_so(sale_order)
            except ValueError as e:
                raise SalesOrderError(str(e))

        sale_order.delivery_count = _pickings_for(sale_order).count()
        sale_order.save(update_fields=["delivery_count"])
        return sale_order

    @classmethod
    @transaction.atomic
    def cancel_sale_order(cls, sale_order):
        """
        Cancel an order and its open deliveries. Refused once goods have left the
        warehouse or the order has been invoiced, because those need a return or a
        credit note instead.
        """
        if sale_order.state == "done":
            raise OrderCancellationError("A locked order cannot be cancelled")
        if sale_order.state == "cancel":
            return sale_order
        if _pickings_for(sale_order).filter(state="done").exists():
            raise OrderCancellationError(
                "Cannot cancel: goods have already been delivered. Create a return instead."
            )
        if sale_order.invoice_count > 0:
            raise OrderCancellationError("Cannot cancel an invoiced order. Cancel the invoice first.")

        for picking in _pickings_for(sale_order).exclude(state__in=("done", "cancel")):
            picking.action_cancel()
        sale_order.state = "cancel"
        sale_order.save(update_fields=["state"])
        return sale_order

    @classmethod
    @transaction.atomic
    def create_invoice_from_so(cls, sale_order):
        """
        Invoice the quantity not yet invoiced on each line. Repeating the action never
        bills the same goods twice.
        """
        from inventory_apps.erp_accounting.models import AccountMove, AccountMoveLine, AccountJournal, AccountAccount

        if sale_order.state not in ("sale", "done"):
            raise OrderStateError("Can only invoice confirmed or locked sale orders")

        pending = [
            line for line in sale_order.lines.all()
            if line.product_uom_qty - line.qty_invoiced > 0
        ]
        if not pending:
            raise AlreadyInvoicedError()

        journal = AccountJournal.objects.filter(journal_type="sale", active=True).first()
        if not journal:
            raise AccountingSetupError("No sales journal configured. Please create one in Accounting.")

        ar_account = AccountAccount.objects.filter(account_type="asset_receivable", active=True).first()
        income_account = AccountAccount.objects.filter(account_type="income", active=True).first()
        line_account = income_account or ar_account
        if not line_account:
            raise AccountingSetupError(
                "No income or receivable account configured. Please set up your chart of accounts."
            )

        move = AccountMove.objects.create(
            move_type="out_invoice",
            partner=sale_order.partner,
            journal=journal,
            invoice_origin=sale_order.name,
            sale_order=sale_order,
            currency=sale_order.currency,
        )
        for line in pending:
            quantity = line.product_uom_qty - line.qty_invoiced
            move_line = AccountMoveLine.objects.create(
                move=move,
                product=line.product,
                account=line_account,
                name=line.description or line.product.name,
                quantity=quantity,
                price_unit=line.price_unit,
                discount=line.discount,
            )
            move_line.compute_amount()
            line.qty_invoiced = line.qty_invoiced + quantity
            line.save(update_fields=["qty_invoiced"])

        move.compute_totals()
        sale_order.invoice_count += 1
        sale_order.save(update_fields=["invoice_count"])
        return move
