"""
erp_pos/models.py — Point of Sale: Config, Sessions, Orders, Lines, Payments.
"""
import uuid
from decimal import Decimal
from django.db import models
from django.utils import timezone


class POSPaymentMethod(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    is_cash = models.BooleanField(default=False)
    journal = models.ForeignKey(
        "erp_accounting.AccountJournal", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="pos_payment_methods",
    )
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class POSConfig(models.Model):
    STATE_CHOICES = [("active", "Active"), ("inactive", "Inactive")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    journal = models.ForeignKey(
        "erp_accounting.AccountJournal", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="pos_configs",
        help_text="Default sales journal",
    )
    payment_methods = models.ManyToManyField(
        POSPaymentMethod, blank=True, related_name="configs",
    )
    state = models.CharField(max_length=10, choices=STATE_CHOICES, default="active")
    warehouse = models.ForeignKey(
        "erp_inventory.Warehouse", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="pos_configs",
    )
    receipt_header = models.TextField(blank=True)
    receipt_footer = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def current_session(self):
        return self.sessions.filter(state="opened").first()


class POSSession(models.Model):
    STATE_CHOICES = [
        ("new_session", "New Session"),
        ("opening_control", "Opening Control"),
        ("opened", "Open"),
        ("closing_control", "Closing Control"),
        ("closed", "Closed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    config = models.ForeignKey(POSConfig, on_delete=models.PROTECT, related_name="sessions")
    name = models.CharField(max_length=100, blank=True, db_index=True)
    state = models.CharField(max_length=20, choices=STATE_CHOICES, default="new_session")
    opened_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    opening_notes = models.TextField(blank=True)
    closing_notes = models.TextField(blank=True)
    cash_register_balance_start = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00"),
    )
    cash_register_balance_end = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00"),
    )
    cash_register_difference = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00"), editable=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.name:
            from inventory_apps.erp_base.models import SequenceCounter
            self.name = SequenceCounter.next_sequence("POS")
        self.cash_register_difference = (
            self.cash_register_balance_end - self.cash_register_balance_start
        )
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name or str(self.id)

    def open_session(self, opening_balance: Decimal = Decimal("0.00"), opening_notes: str = ""):
        self.state = "opened"
        self.opened_at = timezone.now()
        self.cash_register_balance_start = opening_balance
        self.opening_notes = opening_notes
        self.save(update_fields=["state", "opened_at", "cash_register_balance_start", "opening_notes"])

    def close_session(self, closing_balance: Decimal = Decimal("0.00"), notes: str = ""):
        self.state = "closed"
        self.closed_at = timezone.now()
        self.cash_register_balance_end = closing_balance
        self.closing_notes = notes
        self.save(
            update_fields=[
                "state", "closed_at", "cash_register_balance_end",
                "closing_notes", "cash_register_difference",
            ]
        )

    @property
    def total_payments(self) -> Decimal:
        from django.db.models import Sum
        result = POSPayment.objects.filter(
            pos_order__session=self,
        ).aggregate(total=Sum("amount"))
        return result["total"] or Decimal("0.00")

    @property
    def order_count(self) -> int:
        return self.orders.filter(state__in=["paid", "done", "invoiced"]).count()


class POSOrder(models.Model):
    STATE_CHOICES = [
        ("draft", "New"),
        ("cancel", "Cancelled"),
        ("paid", "Paid"),
        ("done", "Posted"),
        ("invoiced", "Invoiced"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, blank=True, db_index=True)
    session = models.ForeignKey(POSSession, on_delete=models.PROTECT, related_name="orders")
    partner = models.ForeignKey(
        "erp_base.Partner", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="pos_orders",
    )
    state = models.CharField(max_length=10, choices=STATE_CHOICES, default="draft")
    date_order = models.DateTimeField(default=timezone.now)

    amount_tax = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    amount_total = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    amount_paid = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    amount_return = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))

    note = models.TextField(blank=True)
    invoice = models.OneToOneField(
        "erp_accounting.AccountMove", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="pos_order",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_order"]

    def save(self, *args, **kwargs):
        if not self.name:
            from inventory_apps.erp_base.models import SequenceCounter
            self.name = SequenceCounter.next_sequence("ORDER")
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name or str(self.id)

    def compute_totals(self):
        tax_total = Decimal("0.00")
        total = Decimal("0.00")
        for line in self.lines.all():
            tax_total += line.price_tax
            total += line.price_subtotal_incl
        paid = sum(p.amount for p in self.payments.all())
        self.amount_tax = tax_total
        self.amount_total = total
        self.amount_paid = paid
        self.amount_return = max(paid - total, Decimal("0.00"))
        self.save(
            update_fields=["amount_tax", "amount_total", "amount_paid", "amount_return"]
        )

    def action_paid(self):
        from inventory_apps.erp_pos.services import POSService
        POSService.process_payment(self)


class POSOrderLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(POSOrder, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(
        "erp_base.ProductVariant", on_delete=models.PROTECT, related_name="pos_lines",
    )
    qty = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("1.0000"))
    price_unit = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0.0000"))
    discount = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    tax_exempt = models.BooleanField(
        default=False, help_text="When set, this line's taxes are removed from the order total.",
    )
    price_subtotal = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00"), editable=False,
    )
    price_tax = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00"), editable=False,
    )
    price_subtotal_incl = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00"), editable=False,
    )
    note = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["id"]

    def save(self, *args, **kwargs):
        base = self.price_unit * self.qty
        disc = base * (self.discount / Decimal("100"))
        self.price_subtotal = (base - disc).quantize(Decimal("0.01"))
        tax_total = Decimal("0.00")
        if self.product_id and not self.tax_exempt:
            for tax in self.product.taxes.filter(active=True):
                tax_total += tax.compute_amount(self.price_subtotal)
        self.price_tax = tax_total
        self.price_subtotal_incl = self.price_subtotal + tax_total
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.product.name} x {self.qty}"


class POSPayment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pos_order = models.ForeignKey(POSOrder, on_delete=models.CASCADE, related_name="payments")
    payment_method = models.ForeignKey(
        POSPaymentMethod, on_delete=models.PROTECT, related_name="pos_payments",
    )
    amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    payment_date = models.DateTimeField(default=timezone.now)
    session = models.ForeignKey(
        POSSession, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="payments",
    )

    class Meta:
        ordering = ["-payment_date"]

    def __str__(self):
        return f"{self.payment_method.name}: {self.amount}"
