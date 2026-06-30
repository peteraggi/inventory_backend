# pos_app/models.py

from django.db import models
import uuid
from django.core.validators import MinValueValidator
from decimal import Decimal
from django.utils import timezone

from inventory_core import settings

# ─── STORE & ROLE ─────────────────────────────────────────────────────────────


class Store(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, unique=True, db_index=True)
    code = models.CharField(max_length=50, unique=True, db_index=True)
    address = models.TextField(blank=True, null=True)
    phone = models.CharField(max_length=50, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal("0.0750"),
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Default VAT rate (e.g. 0.0750 for 7.5%)",
    )
    currency = models.CharField(max_length=3, default="NGN")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})"


class Role(models.Model):
    ROLE_CHOICES = (
        ("salesperson", "Salesperson"),
        ("owner", "Store Owner"),
        ("manager", "Store Manager"),
        ("accountant", "Accountant"),
        ("purchasing", "Purchasing Officer"),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=50, choices=ROLE_CHOICES, unique=True)
    display_name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    permissions = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.display_name


# ─── CONTACTS (Vendors & Customers) ───────────────────────────────────────────


class Contact(models.Model):
    CONTACT_TYPE_CHOICES = (
        ("vendor", "Vendor"),
        ("customer", "Customer"),
        ("both", "Vendor & Customer"),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="contacts")
    name = models.CharField(max_length=255)
    contact_type = models.CharField(
        max_length=10, choices=CONTACT_TYPE_CHOICES, default="customer"
    )
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=50, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    state = models.CharField(max_length=100, blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True, default="Nigeria")
    tax_id = models.CharField(
        max_length=100, blank=True, null=True, help_text="TIN / VAT number"
    )
    payment_terms_days = models.PositiveIntegerField(
        default=30, help_text="Net payment days"
    )
    credit_limit = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        unique_together = ["store", "name", "contact_type"]

    def __str__(self):
        return f"{self.name} ({self.get_contact_type_display()})"

    @property
    def is_vendor(self):
        return self.contact_type in ("vendor", "both")

    @property
    def is_customer(self):
        return self.contact_type in ("customer", "both")


# ─── ACCOUNTING ───────────────────────────────────────────────────────────────


class Account(models.Model):
    ACCOUNT_TYPE_CHOICES = (
        ("asset", "Asset"),
        ("liability", "Liability"),
        ("equity", "Equity"),
        ("revenue", "Revenue"),
        ("cogs", "Cost of Goods Sold"),
        ("expense", "Expense"),
    )
    NORMAL_BALANCE_CHOICES = (
        ("debit", "Debit"),
        ("credit", "Credit"),
    )
    NORMAL_BALANCE_MAP = {
        "asset": "debit",
        "expense": "debit",
        "cogs": "debit",
        "liability": "credit",
        "equity": "credit",
        "revenue": "credit",
    }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="accounts")
    code = models.CharField(max_length=20, db_index=True)
    name = models.CharField(max_length=255)
    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPE_CHOICES)
    normal_balance = models.CharField(
        max_length=6, choices=NORMAL_BALANCE_CHOICES, default="debit"
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    is_system = models.BooleanField(
        default=False, help_text="System accounts cannot be deleted"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ["store", "code"]
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} - {self.name}"

    def save(self, *args, **kwargs):
        self.normal_balance = self.NORMAL_BALANCE_MAP.get(self.account_type, "debit")
        super().save(*args, **kwargs)


class Journal(models.Model):
    JOURNAL_TYPE_CHOICES = (
        ("sale", "Sales Journal"),
        ("purchase", "Purchase Journal"),
        ("cash", "Cash Journal"),
        ("bank", "Bank Journal"),
        ("inventory", "Inventory Valuation Journal"),
        ("general", "General Journal"),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="journals")
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=10)
    journal_type = models.CharField(max_length=20, choices=JOURNAL_TYPE_CHOICES)
    default_debit_account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="debit_journals",
    )
    default_credit_account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="credit_journals",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ["store", "code"]
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})"


class JournalEntry(models.Model):
    STATUS_CHOICES = (
        ("draft", "Draft"),
        ("posted", "Posted"),
        ("cancelled", "Cancelled"),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey(
        Store, on_delete=models.CASCADE, related_name="journal_entries"
    )
    journal = models.ForeignKey(
        Journal, on_delete=models.PROTECT, related_name="entries"
    )
    reference = models.CharField(max_length=100, blank=True)
    date = models.DateField(default=timezone.now)
    memo = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    total_debit = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    total_credit = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    source_type = models.CharField(
        max_length=50,
        blank=True,
        help_text="sales_invoice | vendor_bill | payment | stock_move",
    )
    source_id = models.UUIDField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="journal_entries",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date", "-created_at"]
        verbose_name_plural = "Journal Entries"

    def __str__(self):
        return f"JE-{self.reference or str(self.id)[:8]} ({self.status})"

    def post(self):
        if self.status == "posted":
            return
        lines = self.lines.all()
        total_d = sum(l.debit for l in lines)
        total_c = sum(l.credit for l in lines)
        if total_d != total_c:
            raise ValueError(f"Journal entry not balanced: DR {total_d} ≠ CR {total_c}")
        self.total_debit = total_d
        self.total_credit = total_c
        self.status = "posted"
        self.posted_at = timezone.now()
        self.save()


class JournalEntryLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    journal_entry = models.ForeignKey(
        JournalEntry, on_delete=models.CASCADE, related_name="lines"
    )
    account = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="journal_lines"
    )
    description = models.CharField(max_length=255, blank=True)
    debit = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    credit = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    partner = models.ForeignKey(
        Contact,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="journal_lines",
    )

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.account.code} DR:{self.debit} CR:{self.credit}"


# ─── CATEGORIES & PRODUCTS ────────────────────────────────────────────────────


class Category(models.Model):
    COST_METHOD_CHOICES = (
        ("avco", "Average Cost (AVco)"),
        ("fifo", "First In First Out (FIFO)"),
        ("lifo", "Last In First Out (LIFO)"),
        ("standard", "Standard Cost"),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey(
        Store, on_delete=models.CASCADE, related_name="categories"
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="subcategories",
    )
    cost_method = models.CharField(
        max_length=10, choices=COST_METHOD_CHOICES, default="avco"
    )
    income_account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="category_income",
        help_text="Revenue account for sales",
    )
    cogs_account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="category_cogs",
        help_text="Cost of goods sold account",
    )
    inventory_account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="category_inventory",
        help_text="Inventory asset account",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        unique_together = ["store", "name"]
        verbose_name_plural = "Categories"

    def __str__(self):
        return f"{self.store.name} - {self.name}"


class Product(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="products")
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
    )
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=100, db_index=True)
    description = models.TextField(blank=True)
    price = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    cost = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Last purchase cost",
    )
    avg_cost = models.DecimalField(
        max_digits=12,
        decimal_places=6,
        default=Decimal("0.000000"),
        help_text="Running average cost (AVco) — updated automatically on each receipt",
    )
    standard_cost = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Fixed cost for Standard costing method",
    )
    stock = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        default=Decimal("0.0000"),
        help_text="Current stock quantity",
    )
    stock_value = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Total inventory value at current avg cost",
    )
    low_stock_threshold = models.IntegerField(default=10)
    barcode = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    image_url = models.URLField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_products",
    )

    class Meta:
        ordering = ["name"]
        unique_together = ["store", "code"]
        indexes = [
            models.Index(fields=["store", "is_active"]),
            models.Index(fields=["store", "code"]),
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"

    @property
    def is_low_stock(self):
        return self.stock <= self.low_stock_threshold

    @property
    def cost_method(self):
        return self.category.cost_method if self.category else "avco"

    def update_avco(self, new_qty, new_unit_cost):
        """Recalculate average cost after a purchase receipt (AVco method)."""
        current_value = self.stock * self.avg_cost
        incoming_value = Decimal(str(new_qty)) * Decimal(str(new_unit_cost))
        new_total_qty = self.stock + Decimal(str(new_qty))
        if new_total_qty > 0:
            self.avg_cost = (current_value + incoming_value) / new_total_qty
        self.stock_value = new_total_qty * self.avg_cost
        self.stock = new_total_qty
        self.cost = Decimal(str(new_unit_cost))

    def consume_stock(self, qty):
        """Reduce stock on sale/delivery. Returns unit cost used for COGS."""
        qty = Decimal(str(qty))
        unit_cost = self.avg_cost
        self.stock = max(Decimal("0"), self.stock - qty)
        self.stock_value = self.stock * self.avg_cost
        return unit_cost


# ─── STOCK LAYERS (FIFO / LIFO) ───────────────────────────────────────────────


class StockLayer(models.Model):
    """Purchase lots — consumed in FIFO/LIFO order during sales."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey(
        Store, on_delete=models.CASCADE, related_name="stock_layers"
    )
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="stock_layers"
    )
    quantity_in = models.DecimalField(max_digits=14, decimal_places=4)
    quantity_remaining = models.DecimalField(max_digits=14, decimal_places=4)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=6)
    source_type = models.CharField(max_length=50, default="purchase")
    source_id = models.UUIDField(null=True, blank=True)
    date = models.DateField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "created_at"]

    def __str__(self):
        return f"{self.product.code} | {self.quantity_remaining} @ {self.unit_cost}"


class StockMove(models.Model):
    """Audit trail for every inventory movement."""

    MOVE_TYPE_CHOICES = (
        ("purchase_receipt", "Purchase Receipt"),
        ("pos_sale", "POS Sale"),
        ("sales_delivery", "Sales Order Delivery"),
        ("return_in", "Return In"),
        ("return_out", "Return Out"),
        ("adjustment_in", "Stock Adjustment In"),
        ("adjustment_out", "Stock Adjustment Out"),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey(
        Store, on_delete=models.CASCADE, related_name="stock_moves"
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="stock_moves"
    )
    move_type = models.CharField(max_length=30, choices=MOVE_TYPE_CHOICES)
    quantity = models.DecimalField(
        max_digits=14, decimal_places=4, help_text="Always positive"
    )
    unit_cost = models.DecimalField(
        max_digits=12, decimal_places=6, default=Decimal("0")
    )
    valuation_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    source_type = models.CharField(max_length=50, blank=True)
    source_id = models.UUIDField(null=True, blank=True)
    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_moves",
    )
    note = models.CharField(max_length=255, blank=True)
    date = models.DateField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.move_type} | {self.product.code} | qty:{self.quantity}"


# ─── PURCHASE ─────────────────────────────────────────────────────────────────


class PurchaseOrder(models.Model):
    STATUS_CHOICES = (
        ("rfq", "Request for Quotation"),
        ("po", "Purchase Order"),
        ("partial", "Partially Received"),
        ("received", "Fully Received"),
        ("billed", "Billed"),
        ("cancelled", "Cancelled"),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey(
        Store, on_delete=models.CASCADE, related_name="purchase_orders"
    )
    po_number = models.CharField(max_length=50, unique=True, db_index=True)
    vendor = models.ForeignKey(
        Contact,
        on_delete=models.PROTECT,
        related_name="purchase_orders",
        limit_choices_to={"contact_type__in": ["vendor", "both"]},
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="rfq")
    order_date = models.DateField(default=timezone.now)
    expected_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    subtotal = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    tax_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    discount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    total = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="purchase_orders_created",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchase_orders_approved",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.po_number} — {self.vendor.name} ({self.get_status_display()})"

    def recalculate_totals(self):
        lines = self.lines.all()
        self.subtotal = sum(l.subtotal for l in lines)
        self.tax_amount = sum(l.tax_amount for l in lines)
        self.total = self.subtotal + self.tax_amount - self.discount
        self.save(update_fields=["subtotal", "tax_amount", "total"])

    def confirm(self):
        if self.status != "rfq":
            raise ValueError("Only an RFQ can be confirmed into a Purchase Order.")
        self.status = "po"
        self.save(update_fields=["status"])


class PurchaseOrderLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    purchase_order = models.ForeignKey(
        PurchaseOrder, on_delete=models.CASCADE, related_name="lines"
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="po_lines"
    )
    description = models.CharField(max_length=255, blank=True)
    quantity = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0.0001"))],
    )
    received_qty = models.DecimalField(
        max_digits=14, decimal_places=4, default=Decimal("0.0000")
    )
    unit_cost = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0"))]
    )
    tax_rate = models.DecimalField(
        max_digits=5, decimal_places=4, default=Decimal("0.0000")
    )
    subtotal = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    tax_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    total = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.purchase_order.po_number} — {self.product.code}"

    @property
    def pending_qty(self):
        return self.quantity - self.received_qty

    def save(self, *args, **kwargs):
        self.subtotal = self.quantity * self.unit_cost
        self.tax_amount = self.subtotal * self.tax_rate
        self.total = self.subtotal + self.tax_amount
        super().save(*args, **kwargs)


class GoodsReceipt(models.Model):
    """Delivery received from vendor — validates and updates stock."""

    STATUS_CHOICES = (
        ("draft", "Draft"),
        ("validated", "Validated"),
        ("cancelled", "Cancelled"),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey(
        Store, on_delete=models.CASCADE, related_name="goods_receipts"
    )
    receipt_number = models.CharField(max_length=50, unique=True, db_index=True)
    purchase_order = models.ForeignKey(
        PurchaseOrder, on_delete=models.PROTECT, related_name="receipts"
    )
    received_date = models.DateField(default=timezone.now)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    notes = models.TextField(blank=True)
    validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="validated_receipts",
    )
    validated_at = models.DateTimeField(null=True, blank=True)
    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="goods_receipts",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-received_date", "-created_at"]

    def __str__(self):
        return f"{self.receipt_number} ({self.get_status_display()})"


class GoodsReceiptLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    goods_receipt = models.ForeignKey(
        GoodsReceipt, on_delete=models.CASCADE, related_name="lines"
    )
    purchase_order_line = models.ForeignKey(
        PurchaseOrderLine, on_delete=models.PROTECT, related_name="receipt_lines"
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="receipt_lines"
    )
    ordered_qty = models.DecimalField(max_digits=14, decimal_places=4)
    received_qty = models.DecimalField(
        max_digits=14, decimal_places=4, validators=[MinValueValidator(Decimal("0"))]
    )
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)

    @property
    def total_value(self):
        return self.received_qty * self.unit_cost

    def __str__(self):
        return f"{self.goods_receipt.receipt_number} — {self.product.code}"


class VendorBill(models.Model):
    STATUS_CHOICES = (
        ("draft", "Draft"),
        ("confirmed", "Confirmed"),
        ("partial", "Partially Paid"),
        ("paid", "Paid"),
        ("cancelled", "Cancelled"),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey(
        Store, on_delete=models.CASCADE, related_name="vendor_bills"
    )
    bill_number = models.CharField(max_length=50, unique=True, db_index=True)
    vendor = models.ForeignKey(
        Contact, on_delete=models.PROTECT, related_name="vendor_bills"
    )
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bills",
    )
    bill_date = models.DateField(default=timezone.now)
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    subtotal = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    tax_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    total = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    amount_paid = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    notes = models.TextField(blank=True)
    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vendor_bills",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="vendor_bills_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-bill_date", "-created_at"]

    def __str__(self):
        return f"{self.bill_number} — {self.vendor.name}"

    @property
    def amount_due(self):
        return self.total - self.amount_paid


class VendorBillLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vendor_bill = models.ForeignKey(
        VendorBill, on_delete=models.CASCADE, related_name="lines"
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bill_lines",
    )
    description = models.CharField(max_length=255, blank=True)
    quantity = models.DecimalField(
        max_digits=14, decimal_places=4, default=Decimal("1.0000")
    )
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)
    tax_rate = models.DecimalField(
        max_digits=5, decimal_places=4, default=Decimal("0.0000")
    )
    subtotal = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    tax_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    total = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bill_lines",
    )

    def save(self, *args, **kwargs):
        self.subtotal = self.quantity * self.unit_cost
        self.tax_amount = self.subtotal * self.tax_rate
        self.total = self.subtotal + self.tax_amount
        super().save(*args, **kwargs)


# ─── SALES ────────────────────────────────────────────────────────────────────


class SalesOrder(models.Model):
    STATUS_CHOICES = (
        ("draft", "Draft"),
        ("confirmed", "Confirmed"),
        ("partial", "Partially Delivered"),
        ("delivered", "Fully Delivered"),
        ("invoiced", "Invoiced"),
        ("paid", "Paid"),
        ("cancelled", "Cancelled"),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey(
        Store, on_delete=models.CASCADE, related_name="sales_orders"
    )
    so_number = models.CharField(max_length=50, unique=True, db_index=True)
    customer = models.ForeignKey(
        Contact,
        on_delete=models.PROTECT,
        related_name="sales_orders",
        limit_choices_to={"contact_type__in": ["customer", "both"]},
    )
    salesperson = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="sales_orders",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    order_date = models.DateField(default=timezone.now)
    delivery_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    subtotal = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    tax_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    discount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    total = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.so_number} — {self.customer.name} ({self.get_status_display()})"

    def recalculate_totals(self):
        lines = self.lines.all()
        self.subtotal = sum(l.subtotal for l in lines)
        self.tax_amount = self.subtotal * self.store.tax_rate
        self.total = self.subtotal + self.tax_amount - self.discount
        self.save(update_fields=["subtotal", "tax_amount", "total"])

    def confirm(self):
        if self.status != "draft":
            raise ValueError("Only a Draft order can be confirmed.")
        self.status = "confirmed"
        self.save(update_fields=["status"])


class SalesOrderLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sales_order = models.ForeignKey(
        SalesOrder, on_delete=models.CASCADE, related_name="lines"
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="so_lines"
    )
    description = models.CharField(max_length=255, blank=True)
    quantity = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0.0001"))],
    )
    delivered_qty = models.DecimalField(
        max_digits=14, decimal_places=4, default=Decimal("0.0000")
    )
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    discount_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00")
    )
    subtotal = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    total = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )

    @property
    def pending_qty(self):
        return self.quantity - self.delivered_qty

    def save(self, *args, **kwargs):
        self.subtotal = self.quantity * self.unit_price
        discount_amount = self.subtotal * (self.discount_pct / Decimal("100"))
        self.total = self.subtotal - discount_amount
        super().save(*args, **kwargs)


class DeliveryNote(models.Model):
    STATUS_CHOICES = (
        ("draft", "Draft"),
        ("delivered", "Delivered"),
        ("cancelled", "Cancelled"),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey(
        Store, on_delete=models.CASCADE, related_name="delivery_notes"
    )
    delivery_number = models.CharField(max_length=50, unique=True, db_index=True)
    sales_order = models.ForeignKey(
        SalesOrder, on_delete=models.PROTECT, related_name="delivery_notes"
    )
    delivery_date = models.DateField(default=timezone.now)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    notes = models.TextField(blank=True)
    delivered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deliveries",
    )
    delivered_at = models.DateTimeField(null=True, blank=True)
    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="delivery_notes",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-delivery_date", "-created_at"]

    def __str__(self):
        return f"{self.delivery_number} ({self.get_status_display()})"


class DeliveryNoteLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    delivery_note = models.ForeignKey(
        DeliveryNote, on_delete=models.CASCADE, related_name="lines"
    )
    sales_order_line = models.ForeignKey(
        SalesOrderLine, on_delete=models.PROTECT, related_name="delivery_lines"
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="delivery_lines"
    )
    ordered_qty = models.DecimalField(max_digits=14, decimal_places=4)
    delivered_qty = models.DecimalField(
        max_digits=14, decimal_places=4, validators=[MinValueValidator(Decimal("0"))]
    )
    unit_cost_at_delivery = models.DecimalField(
        max_digits=12, decimal_places=6, default=Decimal("0")
    )

    def __str__(self):
        return f"{self.delivery_note.delivery_number} — {self.product.code}"


class SalesInvoice(models.Model):
    STATUS_CHOICES = (
        ("draft", "Draft"),
        ("sent", "Sent"),
        ("partial", "Partially Paid"),
        ("paid", "Paid"),
        ("overdue", "Overdue"),
        ("cancelled", "Cancelled"),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey(
        Store, on_delete=models.CASCADE, related_name="sales_invoices"
    )
    invoice_number = models.CharField(max_length=50, unique=True, db_index=True)
    sales_order = models.ForeignKey(
        SalesOrder,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoices",
    )
    customer = models.ForeignKey(
        Contact, on_delete=models.PROTECT, related_name="sales_invoices"
    )
    salesperson = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_invoices",
    )
    invoice_date = models.DateField(default=timezone.now)
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    subtotal = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    tax_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    discount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    total = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    amount_paid = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    notes = models.TextField(blank=True)
    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sales_invoices",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-invoice_date", "-created_at"]

    def __str__(self):
        return f"{self.invoice_number} — {self.customer.name}"

    @property
    def amount_due(self):
        return self.total - self.amount_paid

    def recalculate_totals(self):
        lines = self.lines.all()
        self.subtotal = sum(l.subtotal for l in lines)
        self.tax_amount = self.subtotal * self.store.tax_rate
        self.total = self.subtotal + self.tax_amount - self.discount
        self.save(update_fields=["subtotal", "tax_amount", "total"])


class SalesInvoiceLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sales_invoice = models.ForeignKey(
        SalesInvoice, on_delete=models.CASCADE, related_name="lines"
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoice_lines",
    )
    description = models.CharField(max_length=255, blank=True)
    quantity = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0.0001"))],
    )
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    discount_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00")
    )
    subtotal = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    total = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    income_account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoice_lines_income",
    )
    cogs_account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoice_lines_cogs",
    )
    cost_at_sale = models.DecimalField(
        max_digits=12,
        decimal_places=6,
        default=Decimal("0"),
        help_text="Unit cost captured at time of sale for COGS calculation",
    )

    def save(self, *args, **kwargs):
        self.subtotal = self.quantity * self.unit_price
        discount_amount = self.subtotal * (self.discount_pct / Decimal("100"))
        self.total = self.subtotal - discount_amount
        if self.product:
            if not self.income_account and self.product.category:
                self.income_account = self.product.category.income_account
            if not self.cogs_account and self.product.category:
                self.cogs_account = self.product.category.cogs_account
            if not self.cost_at_sale:
                self.cost_at_sale = self.product.avg_cost
        super().save(*args, **kwargs)


# ─── PAYMENTS ─────────────────────────────────────────────────────────────────


class Payment(models.Model):
    PAYMENT_TYPE_CHOICES = (
        ("inbound", "Customer Payment"),
        ("outbound", "Vendor Payment"),
    )
    PAYMENT_METHOD_CHOICES = (
        ("cash", "Cash"),
        ("bank", "Bank Transfer"),
        ("card", "Card"),
        ("cheque", "Cheque"),
        ("other", "Other"),
    )
    STATUS_CHOICES = (
        ("draft", "Draft"),
        ("confirmed", "Confirmed"),
        ("cancelled", "Cancelled"),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="payments")
    payment_number = models.CharField(max_length=50, unique=True, db_index=True)
    payment_type = models.CharField(max_length=10, choices=PAYMENT_TYPE_CHOICES)
    payment_method = models.CharField(
        max_length=10, choices=PAYMENT_METHOD_CHOICES, default="cash"
    )
    contact = models.ForeignKey(
        Contact, on_delete=models.PROTECT, related_name="payments"
    )
    amount = models.DecimalField(
        max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    date = models.DateField(default=timezone.now)
    reference = models.CharField(
        max_length=100, blank=True, help_text="Bank ref / cheque no."
    )
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    sales_invoice = models.ForeignKey(
        SalesInvoice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments",
    )
    vendor_bill = models.ForeignKey(
        VendorBill,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments",
    )
    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="payments_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.payment_number} — {self.contact.name} — {self.amount}"


# ─── POS INVOICE (kept from original) ─────────────────────────────────────────


class Invoice(models.Model):
    SYNC_STATUS_CHOICES = (
        ("PENDING", "Pending Sync"),
        ("SYNCED", "Synced"),
        ("FAILED", "Failed"),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice_number = models.CharField(max_length=100, unique=True, db_index=True)
    store = models.ForeignKey(
        Store, on_delete=models.CASCADE, related_name="pos_invoices"
    )
    salesperson = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sales_invoices",
    )
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    tax = models.DecimalField(max_digits=12, decimal_places=2)
    discount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    total = models.DecimalField(max_digits=12, decimal_places=2)
    customer_name = models.CharField(max_length=255, blank=True, null=True)
    customer_phone = models.CharField(max_length=50, blank=True, null=True)
    customer_email = models.EmailField(blank=True, null=True)
    notes = models.TextField(blank=True)
    payment_method = models.CharField(max_length=20, default="cash")
    sync_status = models.CharField(
        max_length=20, choices=SYNC_STATUS_CHOICES, default="SYNCED"
    )
    synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["store", "created_at"]),
            models.Index(fields=["salesperson", "created_at"]),
            models.Index(fields=["sync_status"]),
        ]

    def __str__(self):
        return f"{self.invoice_number} — {self.salesperson.name}"


class InvoiceItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="invoice_items"
    )
    product_name = models.CharField(max_length=255)
    product_code = models.CharField(max_length=100)
    quantity = models.IntegerField(validators=[MinValueValidator(1)])
    price = models.DecimalField(max_digits=10, decimal_places=2)
    cost_at_sale = models.DecimalField(
        max_digits=12, decimal_places=6, default=Decimal("0")
    )
    total = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.invoice.invoice_number} — {self.product_code}"

    def save(self, *args, **kwargs):
        self.total = self.quantity * self.price
        super().save(*args, **kwargs)


# ─── SYNC & REPORTING ─────────────────────────────────────────────────────────


class SyncLog(models.Model):
    SYNC_TYPE_CHOICES = (
        ("invoice", "Invoice Sync"),
        ("product", "Product Sync"),
        ("full", "Full Sync"),
    )
    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("in_progress", "In Progress"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sync_logs"
    )
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="sync_logs")
    sync_type = models.CharField(max_length=20, choices=SYNC_TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    items_synced = models.IntegerField(default=0)
    items_failed = models.IntegerField(default=0)
    error_message = models.TextField(blank=True)
    details = models.JSONField(default=dict)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.sync_type} — {self.user.name} — {self.status}"


class DailySales(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey(
        Store, on_delete=models.CASCADE, related_name="daily_sales"
    )
    date = models.DateField(db_index=True)
    total_sales = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    invoice_count = models.IntegerField(default=0)
    items_sold = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ["store", "date"]
        ordering = ["-date"]

    def __str__(self):
        return f"{self.store.name} — {self.date}"
