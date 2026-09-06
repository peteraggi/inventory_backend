"""
erp_accounting/models.py — Chart of Accounts, Journals, Journal Entries (Moves), Payments.
Implements double-entry: every posted AccountMove must have sum(debit) == sum(credit).
"""
import uuid
from decimal import Decimal
from django.db import models
from django.utils import timezone


class AccountGroup(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    code_prefix_start = models.CharField(max_length=20, blank=True)
    code_prefix_end = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ["code_prefix_start"]

    def __str__(self):
        return f"{self.code_prefix_start} - {self.name}"


class AccountAccount(models.Model):
    """Leaf of the Chart of Accounts."""
    ACCOUNT_TYPE_CHOICES = [
        # Balance Sheet
        ("asset_cash", "Cash and Cash Equivalents"),
        ("asset_receivable", "Receivable"),
        ("asset_current", "Current Assets"),
        ("asset_non_current", "Non-current Assets"),
        ("asset_fixed", "Fixed Assets"),
        ("asset_prepayments", "Prepayments"),
        # Liabilities
        ("liability_payable", "Payable"),
        ("liability_credit_card", "Credit Card"),
        ("liability_current", "Current Liabilities"),
        ("liability_non_current", "Non-current Liabilities"),
        # Equity
        ("equity", "Equity"),
        ("equity_unaffected", "Current Year Earnings"),
        # Income
        ("income", "Income"),
        ("income_other", "Other Income"),
        # Expenses
        ("expense", "Expense"),
        ("expense_depreciation", "Depreciation"),
        ("expense_direct_cost", "Cost of Revenue"),
        # Off-balance
        ("off_balance", "Off-Balance Sheet"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=64, db_index=True)
    name = models.CharField(max_length=255)
    account_type = models.CharField(max_length=30, choices=ACCOUNT_TYPE_CHOICES)
    group = models.ForeignKey(
        AccountGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name="accounts",
    )
    currency = models.ForeignKey(
        "erp_base.Currency", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="accounts",
    )
    reconcile = models.BooleanField(
        default=False, help_text="Allow reconciliation (for AR/AP accounts)",
    )
    deprecated = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["code"]
        unique_together = [("code",)]

    def __str__(self):
        return f"{self.code} {self.name}"

    @property
    def is_debit_balance(self) -> bool:
        """Assets and expenses have natural debit balances."""
        return self.account_type.startswith(("asset_", "expense"))


class AccountJournal(models.Model):
    JOURNAL_TYPE_CHOICES = [
        ("sale", "Sales"),
        ("purchase", "Purchase"),
        ("cash", "Cash"),
        ("bank", "Bank"),
        ("general", "Miscellaneous"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=10, unique=True)
    journal_type = models.CharField(max_length=10, choices=JOURNAL_TYPE_CHOICES)
    company = models.ForeignKey(
        "erp_base.Company", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="journals",
    )
    currency = models.ForeignKey(
        "erp_base.Currency", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="journals",
    )
    default_account = models.ForeignKey(
        AccountAccount, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="journal_default",
    )
    suspense_account = models.ForeignKey(
        AccountAccount, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="journal_suspense",
    )
    sequence_prefix = models.CharField(max_length=20, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.code} - {self.name}"


class AccountMove(models.Model):
    """Journal entry (also used as customer invoice, vendor bill, etc.)."""
    MOVE_TYPE_CHOICES = [
        ("entry", "Journal Entry"),
        ("out_invoice", "Customer Invoice"),
        ("out_refund", "Customer Credit Note"),
        ("in_invoice", "Vendor Bill"),
        ("in_refund", "Vendor Credit Note"),
    ]
    STATE_CHOICES = [
        ("draft", "Draft"),
        ("posted", "Posted"),
        ("cancel", "Cancelled"),
    ]
    PAYMENT_STATE_CHOICES = [
        ("not_paid", "Not Paid"),
        ("in_payment", "In Payment"),
        ("paid", "Paid"),
        ("partial", "Partially Paid"),
        ("reversed", "Reversed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, blank=True, db_index=True)
    ref = models.CharField(max_length=255, blank=True)
    move_type = models.CharField(max_length=15, choices=MOVE_TYPE_CHOICES, default="entry")
    state = models.CharField(max_length=10, choices=STATE_CHOICES, default="draft")
    payment_state = models.CharField(
        max_length=10, choices=PAYMENT_STATE_CHOICES, default="not_paid",
    )
    journal = models.ForeignKey(
        AccountJournal, on_delete=models.PROTECT, related_name="moves",
    )
    partner = models.ForeignKey(
        "erp_base.Partner", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="account_moves",
    )
    currency = models.ForeignKey(
        "erp_base.Currency", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="account_moves",
    )
    date = models.DateField(default=timezone.localdate)
    invoice_date = models.DateField(null=True, blank=True)
    invoice_date_due = models.DateField(null=True, blank=True)
    invoice_origin = models.CharField(max_length=255, blank=True)
    narration = models.TextField(blank=True)

    amount_untaxed = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    amount_tax = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    amount_total = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    amount_residual = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    amount_paid = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))

    sale_order = models.ForeignKey(
        "erp_sales.SaleOrder", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="invoices",
    )
    purchase_order = models.ForeignKey(
        "erp_purchase.PurchaseOrder", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="bills",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-created_at"]
        indexes = [
            models.Index(fields=["move_type", "state"]),
            models.Index(fields=["payment_state"]),
        ]

    def __str__(self):
        return self.name or f"{self.move_type}/{self.id}"

    def save(self, *args, **kwargs):
        if not self.name and self.state == "posted":
            from inventory_apps.erp_base.models import SequenceCounter
            prefix_map = {
                "out_invoice": "INV",
                "in_invoice": "BILL",
                "out_refund": "RINV",
                "in_refund": "RBILL",
                "entry": "JE",
            }
            prefix = prefix_map.get(self.move_type, "JE")
            self.name = SequenceCounter.next_sequence(prefix)
        super().save(*args, **kwargs)

    @property
    def is_invoice(self):
        return self.move_type in ("out_invoice", "in_invoice", "out_refund", "in_refund")

    @property
    def is_outbound(self):
        return self.move_type in ("out_invoice", "out_refund")

    def action_post(self):
        from inventory_apps.erp_accounting.services import AccountingService
        AccountingService.post_move(self)

    def action_register_payment(self, amount: Decimal, journal, date=None, memo=""):
        from inventory_apps.erp_accounting.services import AccountingService
        return AccountingService.register_payment(self, amount, journal, date, memo)

    def compute_totals(self):
        lines = self.lines.filter(exclude_from_invoice_tab=False)
        untaxed = sum(l.price_subtotal for l in lines) or Decimal("0.00")
        tax_total = sum(l.tax_amount for l in lines) or Decimal("0.00")
        total = untaxed + tax_total
        paid = self.amount_paid
        self.amount_untaxed = untaxed
        self.amount_tax = tax_total
        self.amount_total = total
        self.amount_residual = max(total - paid, Decimal("0.00"))
        self.save(
            update_fields=[
                "amount_untaxed", "amount_tax", "amount_total", "amount_residual",
            ]
        )
        self._update_payment_state()

    def _update_payment_state(self):
        if self.amount_total == Decimal("0.00"):
            self.payment_state = "paid"
        elif self.amount_paid >= self.amount_total:
            self.payment_state = "paid"
        elif self.amount_paid > Decimal("0.00"):
            self.payment_state = "partial"
        else:
            self.payment_state = "not_paid"
        self.save(update_fields=["payment_state"])


class AccountMoveLine(models.Model):
    """Single debit or credit line of a journal entry."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    move = models.ForeignKey(AccountMove, on_delete=models.CASCADE, related_name="lines")
    sequence = models.PositiveIntegerField(default=10)
    account = models.ForeignKey(
        AccountAccount, on_delete=models.PROTECT, related_name="move_lines",
    )
    partner = models.ForeignKey(
        "erp_base.Partner", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="move_lines",
    )
    currency = models.ForeignKey(
        "erp_base.Currency", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="move_lines",
    )
    name = models.CharField(max_length=500, blank=True)
    date = models.DateField(null=True, blank=True)
    date_maturity = models.DateField(null=True, blank=True)

    # Invoice tab fields
    product = models.ForeignKey(
        "erp_base.ProductVariant", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="move_lines",
    )
    quantity = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("1.0000"))
    price_unit = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0.0000"))
    discount = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    taxes = models.ManyToManyField(
        "erp_base.Tax", blank=True, related_name="account_move_lines",
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

    # Accounting fields
    debit = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    credit = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    balance = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00"), editable=False,
    )
    amount_residual = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00"),
    )
    reconciled = models.BooleanField(default=False)
    exclude_from_invoice_tab = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sequence", "id"]

    def save(self, *args, **kwargs):
        if self.product_id and not self.exclude_from_invoice_tab:
            base = self.price_unit * self.quantity
            disc = base * (self.discount / Decimal("100"))
            self.price_subtotal = (base - disc).quantize(Decimal("0.01"))
        self.balance = self.debit - self.credit
        super().save(*args, **kwargs)

    def compute_amount(self):
        """Recompute tax_amount/price_total from the `taxes` M2M (must be
        called after .taxes.set(...), since the line needs a PK first).
        Falls back to the product's own default taxes when the line has none
        explicitly set — e.g. bills/invoices created directly rather than
        from a purchase/sale order line that already had taxes chosen.
        """
        if not self.product_id or self.exclude_from_invoice_tab:
            return
        taxes = list(self.taxes.all())
        if not taxes and self.product_id:
            if self.move.move_type in ("out_invoice", "out_refund"):
                taxes = list(self.product.taxes.filter(active=True))
            else:
                taxes = list(self.product.supplier_taxes.filter(active=True))
        tax_total = sum((t.compute_amount(self.price_subtotal) for t in taxes), Decimal("0.00"))
        self.tax_amount = tax_total
        self.price_total = self.price_subtotal + tax_total
        models.Model.save(self, update_fields=["tax_amount", "price_total"])

    def __str__(self):
        return f"{self.account.code} Dr:{self.debit} Cr:{self.credit}"


class AccountPayment(models.Model):
    PAYMENT_TYPE_CHOICES = [
        ("outbound", "Send Money"),
        ("inbound", "Receive Money"),
    ]
    PARTNER_TYPE_CHOICES = [
        ("customer", "Customer"),
        ("supplier", "Vendor"),
    ]
    STATE_CHOICES = [
        ("draft", "Draft"),
        ("posted", "Validated"),
        ("sent", "Sent"),
        ("reconciled", "Reconciled"),
        ("cancelled", "Cancelled"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, blank=True)
    payment_type = models.CharField(max_length=10, choices=PAYMENT_TYPE_CHOICES)
    partner_type = models.CharField(max_length=10, choices=PARTNER_TYPE_CHOICES, default="customer")
    partner = models.ForeignKey(
        "erp_base.Partner", on_delete=models.PROTECT, null=True, blank=True,
        related_name="payments",
    )
    journal = models.ForeignKey(
        AccountJournal, on_delete=models.PROTECT, related_name="payments",
    )
    currency = models.ForeignKey(
        "erp_base.Currency", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="payments",
    )
    amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    date = models.DateField(default=timezone.localdate)
    memo = models.CharField(max_length=255, blank=True)
    state = models.CharField(max_length=15, choices=STATE_CHOICES, default="draft")

    # Link to source invoice
    reconcile_move = models.ForeignKey(
        AccountMove, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="payments",
    )
    move = models.OneToOneField(
        AccountMove, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="payment_record",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return self.name or f"Payment {self.amount}"

    def action_post(self):
        from inventory_apps.erp_accounting.services import AccountingService
        AccountingService.post_payment(self)
