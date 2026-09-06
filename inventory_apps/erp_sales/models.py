"""
erp_sales/models.py — Sale Orders, Lines.
"""
import uuid
from decimal import Decimal
from django.db import models
from django.utils import timezone


class SaleOrder(models.Model):
    STATE_CHOICES = [
        ("draft", "Quotation"),
        ("sent", "Quotation Sent"),
        ("sale", "Sales Order"),
        ("done", "Locked"),
        ("cancel", "Cancelled"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=64, unique=True, blank=True, db_index=True)
    partner = models.ForeignKey(
        "erp_base.Partner", on_delete=models.PROTECT, related_name="sale_orders",
    )
    company = models.ForeignKey(
        "erp_base.Company", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="sale_orders",
    )
    state = models.CharField(max_length=10, choices=STATE_CHOICES, default="draft")
    date_order = models.DateTimeField(default=timezone.now)
    validity_date = models.DateField(null=True, blank=True)
    payment_term = models.ForeignKey(
        "erp_base.PaymentTerm", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="sale_orders",
    )
    warehouse = models.ForeignKey(
        "erp_inventory.Warehouse", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="sale_orders",
    )
    salesperson = models.ForeignKey(
        "authentication.User", on_delete=models.SET_NULL, null=True, blank=True,
        db_constraint=False, related_name="sale_orders",
    )
    currency = models.ForeignKey(
        "erp_base.Currency", on_delete=models.PROTECT, null=True, blank=True,
        related_name="sale_orders",
    )
    note = models.TextField(blank=True)
    client_order_ref = models.CharField(max_length=100, blank=True)

    # Totals (computed on save)
    amount_untaxed = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    amount_tax = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    amount_total = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))

    # Linked document counts (denormalised for smart buttons)
    delivery_count = models.PositiveIntegerField(default=0)
    invoice_count = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_order"]
        indexes = [models.Index(fields=["state"])]

    def __str__(self):
        return self.name or str(self.id)

    def save(self, *args, **kwargs):
        if not self.name:
            from inventory_apps.erp_base.models import SequenceCounter
            self.name = SequenceCounter.next_sequence("SO")
        super().save(*args, **kwargs)

    def compute_totals(self):
        untaxed = Decimal("0.00")
        tax_total = Decimal("0.00")
        for line in self.lines.all():
            untaxed += line.price_subtotal
            tax_total += line.tax_amount
        self.amount_untaxed = untaxed
        self.amount_tax = tax_total
        self.amount_total = untaxed + tax_total
        self.save(update_fields=["amount_untaxed", "amount_tax", "amount_total"])

    def action_confirm(self):
        from inventory_apps.erp_sales.services import SalesService
        SalesService.confirm_sale_order(self)

    def action_cancel(self):
        if self.state not in ("done",):
            self.state = "cancel"
            self.save(update_fields=["state"])

    def action_send(self):
        if self.state != "draft":
            raise ValueError(f"Cannot send quotation in state '{self.state}'")
        self.state = "sent"
        self.save(update_fields=["state"])

    @property
    def invoice_status(self):
        lines = self.lines.all()
        if not lines.exists():
            return "nothing_to_invoice"
        invoiced = all(line.qty_invoiced >= line.product_uom_qty for line in lines)
        if invoiced:
            return "invoiced"
        if any(line.qty_invoiced > 0 for line in lines):
            return "to_invoice"
        return "to_invoice"


class SaleOrderLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(SaleOrder, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(
        "erp_base.ProductVariant", on_delete=models.PROTECT, related_name="sale_lines",
    )
    product_uom = models.ForeignKey(
        "erp_base.UnitOfMeasure", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="sale_order_lines",
    )
    description = models.TextField(blank=True)
    product_uom_qty = models.DecimalField(
        max_digits=18, decimal_places=4, default=Decimal("1.0000"),
        help_text="Ordered quantity",
    )
    qty_delivered = models.DecimalField(
        max_digits=18, decimal_places=4, default=Decimal("0.0000"),
    )
    qty_invoiced = models.DecimalField(
        max_digits=18, decimal_places=4, default=Decimal("0.0000"),
    )
    price_unit = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0.0000"))
    discount = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00"),
        help_text="Discount percentage",
    )
    price_subtotal = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00"), editable=False,
    )
    tax_amount = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00"), editable=False,
    )
    price_total = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00"), editable=False,
    )
    sequence = models.PositiveIntegerField(default=10)

    class Meta:
        ordering = ["sequence", "id"]

    def save(self, *args, **kwargs):
        if not self.product_uom_id and self.product_id:
            self.product_uom_id = self.product.product_template.uom_id
        base = self.price_unit * self.product_uom_qty
        disc = base * (self.discount / Decimal("100"))
        self.price_subtotal = (base - disc).quantize(Decimal("0.01"))
        # Tax computed from product's sale taxes
        tax_total = Decimal("0.00")
        if self.product_id:
            for tax in self.product.taxes.filter(active=True):
                tax_total += tax.compute_amount(self.price_subtotal)
        self.tax_amount = tax_total
        self.price_total = self.price_subtotal + tax_total
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.product.name} x {self.product_uom_qty}"
