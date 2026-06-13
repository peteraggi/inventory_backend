# pos_app/models.py file

from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
import uuid
from django.core.validators import MinValueValidator
from decimal import Decimal

from inventory_core import settings


class Store(models.Model):
    """Store/Business entity"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, unique=True, db_index=True)
    code = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="Unique store code (e.g., STORE001)",
    )
    address = models.TextField(blank=True, null=True)
    phone = models.CharField(max_length=50, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal("0.1000"),
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Default tax rate (e.g., 0.1000 for 10%)",
    )
    currency = models.CharField(
        max_length=3, default="USD", help_text="ISO currency code"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Store"
        verbose_name_plural = "Stores"

    def __str__(self):
        return f"{self.name} ({self.code})"


class Role(models.Model):
    """User roles in the system"""

    ROLE_CHOICES = (
        ("salesperson", "Salesperson"),
        ("owner", "Store Owner"),
        ("manager", "Store Manager"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=50, choices=ROLE_CHOICES, unique=True)
    display_name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    permissions = models.JSONField(default=dict, help_text="Role-specific permissions")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.display_name


class Category(models.Model):
    """Product categories"""

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
    """Products in the store"""

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
    code = models.CharField(
        max_length=100, db_index=True, help_text="SKU or product code"
    )
    description = models.TextField(blank=True)

    price = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )
    cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
    )

    stock = models.IntegerField(
        default=0, validators=[MinValueValidator(0)], help_text="Current stock quantity"
    )
    low_stock_threshold = models.IntegerField(
        default=10,
        validators=[MinValueValidator(0)],
        help_text="Alert when stock falls below this",
    )

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


class Invoice(models.Model):
    """Sales invoices"""

    SYNC_STATUS_CHOICES = (
        ("PENDING", "Pending Sync"),
        ("SYNCED", "Synced"),
        ("FAILED", "Failed"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice_number = models.CharField(max_length=100, unique=True, db_index=True)

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="invoices")
    salesperson = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sales_invoices",
        help_text="Salesperson who created this invoice",
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
        return f"{self.invoice_number} - {self.salesperson.name}"

    def calculate_totals(self):
        """Recalculate totals from items"""
        items = self.items.all()
        self.subtotal = sum(item.total for item in items)
        self.tax = self.subtotal * self.store.tax_rate
        self.total = self.subtotal + self.tax - self.discount
        return self.total


class InvoiceItem(models.Model):
    """Items in an invoice"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="invoice_items"
    )

    product_name = models.CharField(
        max_length=255, help_text="Product name at time of sale"
    )
    product_code = models.CharField(
        max_length=100, help_text="Product code at time of sale"
    )

    quantity = models.IntegerField(validators=[MinValueValidator(1)])
    price = models.DecimalField(
        max_digits=10, decimal_places=2, help_text="Price per unit at time of sale"
    )
    total = models.DecimalField(max_digits=12, decimal_places=2)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.invoice.invoice_number} - {self.product_code}"

    def save(self, *args, **kwargs):
        # Calculate total
        self.total = self.quantity * self.price
        super().save(*args, **kwargs)


class SyncLog(models.Model):
    """Log of sync operations"""

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
        return f"{self.sync_type} - {self.user.name} - {self.status}"


class DailySales(models.Model):
    """Aggregated daily sales data"""

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
        return f"{self.store.name} - {self.date}"
