"""
erp_purchase/models.py — Purchase Orders, Lines.
"""
import uuid
from decimal import Decimal
from django.db import models
from django.utils import timezone


class PurchaseOrder(models.Model):
    STATE_CHOICES = [
        ("draft", "RFQ"),
        ("sent", "RFQ Sent"),
        ("purchase", "Purchase Order"),
        ("done", "Locked"),
        ("cancel", "Cancelled"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=64, unique=True, blank=True, db_index=True)
    partner = models.ForeignKey(
        "erp_base.Partner", on_delete=models.PROTECT, related_name="purchase_orders",
    )
    partner_ref = models.CharField(
        max_length=255, blank=True, help_text="Vendor's own quote/order reference",
    )
    company = models.ForeignKey(
        "erp_base.Company", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="purchase_orders",
    )
    state = models.CharField(max_length=10, choices=STATE_CHOICES, default="draft")
    date_order = models.DateTimeField(default=timezone.now)
    date_planned = models.DateTimeField(null=True, blank=True)
    date_approve = models.DateTimeField(null=True, blank=True)
    payment_term = models.ForeignKey(
        "erp_base.PaymentTerm", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="purchase_orders",
    )
    currency = models.ForeignKey(
        "erp_base.Currency", on_delete=models.PROTECT, null=True, blank=True,
        related_name="purchase_orders",
    )
    notes = models.TextField(blank=True)
    origin = models.CharField(max_length=255, blank=True)

    amount_untaxed = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    amount_tax = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    amount_total = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))

    receipt_count = models.PositiveIntegerField(default=0)
    invoice_count = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_order"]

    def __str__(self):
        return self.name or str(self.id)

    def save(self, *args, **kwargs):
        if not self.name:
            from inventory_apps.erp_base.models import SequenceCounter
            self.name = SequenceCounter.next_sequence("PO")
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
        from inventory_apps.erp_purchase.services import PurchaseService
        PurchaseService.confirm_purchase_order(self)

    def action_cancel(self):
        if self.state not in ("done",):
            self.state = "cancel"
            self.save(update_fields=["state"])

    def action_send(self):
        if self.state != "draft":
            raise ValueError(f"Cannot send RFQ in state '{self.state}'")
        self.state = "sent"
        self.save(update_fields=["state"])

    @property
    def billing_status(self) -> str:
        if self.state not in ("purchase", "done"):
            return "nothing_to_bill"
        return "billed" if self.invoice_count > 0 else "to_bill"


class PurchaseOrderLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(
        "erp_base.ProductTemplate", on_delete=models.PROTECT, related_name="purchase_lines",
    )
    description = models.TextField(blank=True)
    product_qty = models.DecimalField(
        max_digits=18, decimal_places=4, default=Decimal("1.0000"),
    )
    qty_received = models.DecimalField(
        max_digits=18, decimal_places=4, default=Decimal("0.0000"),
    )
    qty_billed = models.DecimalField(
        max_digits=18, decimal_places=4, default=Decimal("0.0000"),
    )
    price_unit = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0.0000"))
    taxes = models.ManyToManyField(
        "erp_base.Tax", blank=True, related_name="purchase_order_lines",
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
    date_planned = models.DateTimeField(null=True, blank=True)
    sequence = models.PositiveIntegerField(default=10)

    class Meta:
        ordering = ["sequence", "id"]

    def save(self, *args, **kwargs):
        self.price_subtotal = (self.price_unit * self.product_qty).quantize(Decimal("0.01"))
        super().save(*args, **kwargs)

    def compute_amount(self):
        """Recompute tax_amount/price_total from the (already-saved) taxes M2M.

        Must be called after .taxes.set(...), since the line needs a PK
        before the M2M relation can be queried.
        """
        tax_total = Decimal("0.00")
        for tax in self.taxes.all():
            tax_total += tax.compute_amount(self.price_subtotal)
        self.tax_amount = tax_total
        self.price_total = self.price_subtotal + tax_total
        models.Model.save(self, update_fields=["tax_amount", "price_total"])

    def __str__(self):
        return f"{self.product.name} x {self.product_qty}"

    @property
    def qty_to_receive(self) -> Decimal:
        return max(self.product_qty - self.qty_received, Decimal("0.0000"))
