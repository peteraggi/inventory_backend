"""
erp_base/models.py — Master data: Company, Currency, Partner, Product, UOM, Tax, PaymentTerm.
All models live in the tenant schema (per-tenant isolation via django-tenants).
"""
import uuid
from decimal import Decimal
from django.db import models
from django.utils import timezone


class SequenceCounter(models.Model):
    """Atomic sequence counter for document numbers (SO/2026/00001, etc.)."""
    prefix = models.CharField(max_length=20, unique=True)
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["prefix"]

    def next_value(self):
        self.last_number += 1
        self.save(update_fields=["last_number"])
        return self.last_number

    @classmethod
    def next_sequence(cls, prefix: str, year: int | None = None, digits: int = 5) -> str:
        yr = year or timezone.now().year
        key = f"{prefix}/{yr}"
        counter, _ = cls.objects.select_for_update().get_or_create(prefix=key)
        n = counter.next_value()
        return f"{prefix}/{yr}/{str(n).zfill(digits)}"

    def __str__(self):
        return f"{self.prefix}: {self.last_number}"


# ─── Company ─────────────────────────────────────────────────────────────────


class Currency(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=3, unique=True)  # NGN, USD, EUR
    symbol = models.CharField(max_length=5, default="₦")
    rate = models.DecimalField(
        max_digits=20, decimal_places=6, default=Decimal("1.000000"),
        help_text="Exchange rate relative to company base currency",
    )
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "currencies"
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} ({self.symbol})"


class Company(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    currency = models.ForeignKey(
        Currency, on_delete=models.PROTECT, null=True, blank=True, related_name="companies",
    )
    logo = models.ImageField(upload_to="company/logos/", null=True, blank=True)
    street = models.CharField(max_length=255, blank=True)
    street2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    zip_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=100, default="Nigeria")
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True)
    tax_id = models.CharField(max_length=100, blank=True, help_text="TIN / VAT number")
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "companies"
        ordering = ["name"]

    def __str__(self):
        return self.name


# ─── Partner (Customers & Vendors) ───────────────────────────────────────────


class Partner(models.Model):
    PARTNER_TYPE_CHOICES = [
        ("contact", "Contact"),
        ("company", "Company"),
        ("individual", "Individual"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        Company, on_delete=models.SET_NULL, null=True, blank=True, related_name="partners",
    )
    parent = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="children",
    )
    name = models.CharField(max_length=255, db_index=True)
    partner_type = models.CharField(
        max_length=20, choices=PARTNER_TYPE_CHOICES, default="individual",
    )
    is_customer = models.BooleanField(default=True)
    is_vendor = models.BooleanField(default=False)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    mobile = models.CharField(max_length=50, blank=True)
    street = models.CharField(max_length=255, blank=True)
    street2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    zip_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=100, default="Nigeria")
    tax_id = models.CharField(max_length=100, blank=True)
    website = models.URLField(blank=True)
    notes = models.TextField(blank=True)
    credit_limit = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    payment_term = models.ForeignKey(
        "PaymentTerm", on_delete=models.SET_NULL, null=True, blank=True, related_name="partners",
    )
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["is_customer"]),
            models.Index(fields=["is_vendor"]),
        ]

    def __str__(self):
        return self.name

    @property
    def display_address(self):
        parts = [self.street, self.city, self.state, self.country]
        return ", ".join(p for p in parts if p)


# ─── Payment Terms ────────────────────────────────────────────────────────────


class PaymentTerm(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    note = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class PaymentTermLine(models.Model):
    VALUE_CHOICES = [
        ("balance", "Balance"),
        ("percent", "Percent"),
        ("fixed", "Fixed Amount"),
    ]
    payment_term = models.ForeignKey(PaymentTerm, on_delete=models.CASCADE, related_name="lines")
    value = models.CharField(max_length=10, choices=VALUE_CHOICES, default="balance")
    value_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    days = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.payment_term.name}: {self.value} in {self.days}d"


# ─── Unit of Measure ──────────────────────────────────────────────────────────


class UomCategory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name = "UOM Category"
        verbose_name_plural = "UOM Categories"
        ordering = ["name"]

    def __str__(self):
        return self.name


class UnitOfMeasure(models.Model):
    UOM_TYPE_CHOICES = [
        ("reference", "Reference Unit"),
        ("smaller", "Smaller than reference"),
        ("bigger", "Bigger than reference"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    category = models.ForeignKey(UomCategory, on_delete=models.CASCADE, related_name="uoms")
    uom_type = models.CharField(max_length=10, choices=UOM_TYPE_CHOICES, default="reference")
    factor = models.DecimalField(
        max_digits=20, decimal_places=6, default=Decimal("1.000000"),
        help_text="How many of this UOM equals the reference UOM",
    )
    rounding = models.DecimalField(max_digits=10, decimal_places=6, default=Decimal("0.01"))
    active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Unit of Measure"
        verbose_name_plural = "Units of Measure"
        ordering = ["category__name", "name"]

    def __str__(self):
        return self.name


# ─── Product ──────────────────────────────────────────────────────────────────


class ProductCategory(models.Model):
    COSTING_METHOD_CHOICES = [
        ("standard", "Standard Price"),
        ("avco", "Average Cost (AVCO)"),
        ("fifo", "First In First Out (FIFO)"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    complete_name = models.CharField(max_length=512, blank=True, editable=False)
    parent = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="children",
    )
    costing_method = models.CharField(
        max_length=10, choices=COSTING_METHOD_CHOICES, default="avco",
    )
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "product categories"
        ordering = ["complete_name"]

    def save(self, *args, **kwargs):
        if self.parent:
            self.complete_name = f"{self.parent.complete_name} / {self.name}"
        else:
            self.complete_name = self.name
        super().save(*args, **kwargs)

    def __str__(self):
        return self.complete_name


class TaxGroup(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    sequence = models.PositiveIntegerField(default=10)

    class Meta:
        ordering = ["sequence", "name"]

    def __str__(self):
        return self.name


class Tax(models.Model):
    TYPE_TAX_USE_CHOICES = [
        ("sale", "Sales"),
        ("purchase", "Purchases"),
        ("none", "None"),
    ]
    AMOUNT_TYPE_CHOICES = [
        ("percent", "Percentage"),
        ("fixed", "Fixed Amount"),
        ("division", "% of Price Tax Included"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    type_tax_use = models.CharField(
        max_length=10, choices=TYPE_TAX_USE_CHOICES, default="sale",
    )
    amount_type = models.CharField(
        max_length=10, choices=AMOUNT_TYPE_CHOICES, default="percent",
    )
    amount = models.DecimalField(
        max_digits=10, decimal_places=4, default=Decimal("0.0000"),
        help_text="Tax rate as a percentage (e.g. 7.5 for 7.5%)",
    )
    tax_group = models.ForeignKey(
        TaxGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name="taxes",
    )
    include_base_amount = models.BooleanField(default=False)
    is_base_affected = models.BooleanField(default=True)
    price_include = models.BooleanField(default=False, help_text="Tax included in price")
    active = models.BooleanField(default=True)
    description = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.amount}%)"

    def compute_amount(self, base: Decimal) -> Decimal:
        if self.amount_type == "percent":
            return (base * self.amount / Decimal("100")).quantize(Decimal("0.01"))
        if self.amount_type == "fixed":
            return self.amount
        if self.amount_type == "division":
            return (base - base / (1 + self.amount / Decimal("100"))).quantize(Decimal("0.01"))
        return Decimal("0.00")


class ProductTemplate(models.Model):
    PRODUCT_TYPE_CHOICES = [
        ("storable", "Storable Product"),
        ("consumable", "Consumable"),
        ("service", "Service"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, db_index=True)
    internal_reference = models.CharField(
        max_length=100, blank=True, db_index=True,
        help_text="Internal reference / SKU",
    )
    barcode = models.CharField(max_length=100, blank=True, db_index=True)
    description = models.TextField(blank=True)
    description_sale = models.TextField(blank=True)
    description_purchase = models.TextField(blank=True)
    product_type = models.CharField(
        max_length=15, choices=PRODUCT_TYPE_CHOICES, default="storable",
    )
    category = models.ForeignKey(
        ProductCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name="products",
    )
    uom = models.ForeignKey(
        UnitOfMeasure, on_delete=models.PROTECT, related_name="products",
        null=True, blank=True,
    )
    purchase_uom = models.ForeignKey(
        UnitOfMeasure, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="purchase_products",
    )
    sale_price = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00"),
    )
    standard_price = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00"),
        help_text="Cost / standard price",
    )
    taxes = models.ManyToManyField(
        Tax, blank=True, related_name="sale_products",
        limit_choices_to={"type_tax_use": "sale"},
    )
    supplier_taxes = models.ManyToManyField(
        Tax, blank=True, related_name="purchase_products",
        limit_choices_to={"type_tax_use": "purchase"},
    )
    active = models.BooleanField(default=True)
    can_be_sold = models.BooleanField(default=True)
    can_be_purchased = models.BooleanField(default=True)
    image = models.ImageField(upload_to="products/", null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["active"]),
            models.Index(fields=["product_type"]),
        ]

    def __str__(self):
        return self.name

    @property
    def display_name(self):
        ref = f"[{self.internal_reference}] " if self.internal_reference else ""
        return f"{ref}{self.name}"

    @property
    def qty_on_hand(self) -> Decimal:
        from inventory_apps.erp_inventory.models import StockQuant
        from django.db.models import Sum
        result = StockQuant.objects.filter(
            product=self,
            location__usage="internal",
        ).aggregate(total=Sum("quantity"))
        return result["total"] or Decimal("0.00")

    @property
    def qty_available(self) -> Decimal:
        from inventory_apps.erp_inventory.models import StockQuant
        from django.db.models import Sum
        result = StockQuant.objects.filter(
            product=self,
            location__usage="internal",
        ).aggregate(
            total=models.ExpressionWrapper(
                models.Sum("quantity") - models.Sum("reserved_quantity"),
                output_field=models.DecimalField(),
            )
        )
        return result["total"] or Decimal("0.00")
