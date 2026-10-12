"""
erp_sales/services.py — SalesService: confirm SO, create invoice, create delivery.
"""
from decimal import Decimal
from django.db import transaction


class SalesService:

    @classmethod
    @transaction.atomic
    def confirm_sale_order(cls, sale_order):
        from inventory_apps.erp_inventory.services import StockService
        if sale_order.state not in ("draft", "sent"):
            raise ValueError(f"Cannot confirm order in state '{sale_order.state}'")

        sale_order.state = "sale"
        sale_order.save(update_fields=["state"])

        # Create delivery picking if any storable products
        storable_lines = [
            l for l in sale_order.lines.all()
            if l.product.product_type == "storable"
        ]
        if storable_lines:
            picking = StockService.create_delivery_from_so(sale_order)
            sale_order.delivery_count = 1
            sale_order.save(update_fields=["delivery_count"])

        return sale_order

    @classmethod
    @transaction.atomic
    def create_invoice_from_so(cls, sale_order):
        from inventory_apps.erp_accounting.models import AccountMove, AccountMoveLine, AccountJournal
        if sale_order.state not in ("sale", "done"):
            raise ValueError("Can only invoice confirmed or locked sale orders")

        journal = AccountJournal.objects.filter(journal_type="sale", active=True).first()
        if not journal:
            raise ValueError("No sales journal configured. Please create one in Accounting.")

        move = AccountMove.objects.create(
            move_type="out_invoice",
            partner=sale_order.partner,
            journal=journal,
            invoice_origin=sale_order.name,
            sale_order=sale_order,
            currency=sale_order.currency,
        )
        # Find the AR account
        from inventory_apps.erp_accounting.models import AccountAccount
        ar_account = AccountAccount.objects.filter(
            account_type="asset_receivable", active=True
        ).first()
        income_account = AccountAccount.objects.filter(
            account_type="income", active=True
        ).first()
        line_account = income_account or ar_account
        if not line_account:
            raise ValueError(
                "No income or receivable account configured. Please set up your chart of accounts."
            )

        for line in sale_order.lines.all():
            move_line = AccountMoveLine.objects.create(
                move=move,
                product=line.product,
                account=line_account,
                name=line.description or line.product.name,
                quantity=line.product_uom_qty,
                price_unit=line.price_unit,
                discount=line.discount,
            )
            move_line.compute_amount()
            line.qty_invoiced = line.product_uom_qty
            line.save(update_fields=["qty_invoiced"])

        move.compute_totals()

        sale_order.invoice_count += 1
        sale_order.save(update_fields=["invoice_count"])
        return move

    # Fields copied verbatim when a quotation is revised.
    REVISION_COPY_FIELDS = [
        "partner_id", "company_id", "payment_term_id", "warehouse_id", "currency_id",
        "note", "client_order_ref",
        "delivery_days", "delivery_words", "validity_days", "validity_words",
        "payment_grace_days", "payment_words", "initial_payment_percentage",
        "last_payment_percentage", "payment_method_words", "bank_details",
    ]
    REVISION_LINE_COPY_FIELDS = [
        "product_id", "product_uom_id", "description", "product_uom_qty",
        "price_unit", "discount", "sequence",
    ]

    @classmethod
    @transaction.atomic
    def create_revision(cls, sale_order, user=None):
        """Copy a quotation into a new draft revision of the same root
        quotation (OAS "quotation variant"). The original is left untouched so
        the customer can be offered alternatives side by side."""
        from django.db.models import Max
        from inventory_apps.erp_sales.models import SaleOrder, SaleOrderLine

        if sale_order.state not in ("draft", "sent"):
            raise ValueError("Only quotations (not confirmed orders) can be revised")

        root = sale_order.revision_of or sale_order
        last = root.revisions.aggregate(m=Max("revision"))["m"] or root.revision
        number = last + 1

        new_order = SaleOrder(
            name=f"{root.name}-R{number}",
            revision_of=root,
            revision=number,
            salesperson=user or sale_order.salesperson,
            **{f: getattr(sale_order, f) for f in cls.REVISION_COPY_FIELDS},
        )
        new_order.save()
        for line in sale_order.lines.all():
            SaleOrderLine.objects.create(
                order=new_order,
                **{f: getattr(line, f) for f in cls.REVISION_LINE_COPY_FIELDS},
            )
        new_order.compute_totals()
        return new_order
