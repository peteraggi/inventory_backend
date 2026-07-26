"""
erp_inventory/models.py — Warehouse, Locations, Stock Pickings, Moves, Quants, Lots.
"""
import uuid
from decimal import Decimal
from django.db import models
from django.utils import timezone


class Warehouse(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    short_name = models.CharField(max_length=10, help_text="Short code (e.g. WH)")
    company = models.ForeignKey(
        "erp_base.Company", on_delete=models.CASCADE, related_name="warehouses",
        null=True, blank=True,
    )
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.short_name})"

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new:
            self._create_default_locations()
            self._create_default_picking_types()

    def _create_default_locations(self):
        view_loc = StockLocation.objects.create(
            name=self.short_name, usage="view", is_scrap=False,
        )
        input_loc = StockLocation.objects.create(
            name="Input", usage="internal", parent=view_loc, warehouse=self,
        )
        stock_loc = StockLocation.objects.create(
            name="Stock", usage="internal", parent=view_loc, warehouse=self,
        )
        output_loc = StockLocation.objects.create(
            name="Output", usage="internal", parent=view_loc, warehouse=self,
        )
        self.lot_stock_location = stock_loc
        self.wh_input_location = input_loc
        self.wh_output_location = output_loc
        self.view_location = view_loc
        Warehouse.objects.filter(pk=self.pk).update(
            lot_stock_location=stock_loc,
            wh_input_location=input_loc,
            wh_output_location=output_loc,
            view_location=view_loc,
        )

    def _create_default_picking_types(self):
        # Virtual locations shared across all warehouses — get_or_create since
        # nothing else seeds these; without them Receipts/Delivery Orders
        # picking types below would silently never get created.
        partner_loc, _ = StockLocation.objects.get_or_create(
            usage="supplier", defaults={"name": "Vendors"},
        )
        customer_loc, _ = StockLocation.objects.get_or_create(
            usage="customer", defaults={"name": "Customers"},
        )
        stock_loc = getattr(self, "lot_stock_location", None) or StockLocation.objects.filter(
            warehouse=self, name="Stock"
        ).first()

        if partner_loc and stock_loc:
            StockPickingType.objects.create(
                name="Receipts",
                code="incoming",
                warehouse=self,
                default_location_src=partner_loc,
                default_location_dest=stock_loc,
                sequence_prefix=f"{self.short_name}/IN/",
            )
        if stock_loc and customer_loc:
            StockPickingType.objects.create(
                name="Delivery Orders",
                code="outgoing",
                warehouse=self,
                default_location_src=stock_loc,
                default_location_dest=customer_loc,
                sequence_prefix=f"{self.short_name}/OUT/",
            )
        if stock_loc:
            StockPickingType.objects.create(
                name="Internal Transfers",
                code="internal",
                warehouse=self,
                default_location_src=stock_loc,
                default_location_dest=stock_loc,
                sequence_prefix=f"{self.short_name}/INT/",
            )


# Add FK fields to Warehouse that reference locations (can't do circular at class definition)
Warehouse.add_to_class(
    "lot_stock_location",
    models.ForeignKey(
        "StockLocation", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="warehouse_stock", db_column="lot_stock_location_id",
    ),
)
Warehouse.add_to_class(
    "wh_input_location",
    models.ForeignKey(
        "StockLocation", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="warehouse_input", db_column="wh_input_location_id",
    ),
)
Warehouse.add_to_class(
    "wh_output_location",
    models.ForeignKey(
        "StockLocation", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="warehouse_output", db_column="wh_output_location_id",
    ),
)
Warehouse.add_to_class(
    "view_location",
    models.ForeignKey(
        "StockLocation", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="warehouse_view", db_column="view_location_id",
    ),
)


class StockLocation(models.Model):
    USAGE_CHOICES = [
        ("supplier", "Vendor Location"),
        ("view", "View"),
        ("internal", "Internal Location"),
        ("customer", "Customer Location"),
        ("inventory", "Inventory Adjustments"),
        ("production", "Production"),
        ("transit", "Transit Location"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    complete_name = models.CharField(max_length=1000, blank=True, editable=False)
    usage = models.CharField(max_length=20, choices=USAGE_CHOICES, default="internal")
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True, related_name="children",
    )
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.CASCADE, null=True, blank=True, related_name="locations",
    )
    is_scrap = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["complete_name"]

    def save(self, *args, **kwargs):
        if self.parent:
            self.complete_name = f"{self.parent.complete_name}/{self.name}"
        else:
            self.complete_name = self.name
        super().save(*args, **kwargs)

    def __str__(self):
        return self.complete_name or self.name

    @property
    def qty_on_hand(self) -> Decimal:
        from django.db.models import Sum
        result = StockQuant.objects.filter(location=self).aggregate(total=Sum("quantity"))
        return result["total"] or Decimal("0.00")


class StockPickingType(models.Model):
    CODE_CHOICES = [
        ("incoming", "Receipt"),
        ("outgoing", "Delivery"),
        ("internal", "Internal Transfer"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=10, choices=CODE_CHOICES)
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.CASCADE, null=True, blank=True, related_name="picking_types",
    )
    default_location_src = models.ForeignKey(
        StockLocation, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="picking_type_src",
    )
    default_location_dest = models.ForeignKey(
        StockLocation, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="picking_type_dest",
    )
    sequence_prefix = models.CharField(max_length=50, default="WH/")
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["warehouse__name", "code"]

    def __str__(self):
        return self.name


class StockLot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, db_index=True)
    product = models.ForeignKey(
        "erp_base.ProductTemplate", on_delete=models.CASCADE, related_name="lots",
    )
    ref = models.CharField(max_length=100, blank=True)
    expiration_date = models.DateTimeField(null=True, blank=True)
    use_date = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = [("name", "product")]

    def __str__(self):
        return f"{self.name} ({self.product.name})"


class StockPicking(models.Model):
    STATE_CHOICES = [
        ("draft", "Draft"),
        ("waiting", "Waiting Another Operation"),
        ("confirmed", "Waiting"),
        ("assigned", "Ready"),
        ("done", "Done"),
        ("cancel", "Cancelled"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, blank=True, db_index=True)
    picking_type = models.ForeignKey(
        StockPickingType, on_delete=models.PROTECT, related_name="pickings",
    )
    partner = models.ForeignKey(
        "erp_base.Partner", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="pickings",
    )
    state = models.CharField(max_length=15, choices=STATE_CHOICES, default="draft")
    scheduled_date = models.DateTimeField(default=timezone.now)
    date_done = models.DateTimeField(null=True, blank=True)
    origin = models.CharField(max_length=255, blank=True, help_text="Source document reference")
    note = models.TextField(blank=True)
    location_src = models.ForeignKey(
        StockLocation, on_delete=models.PROTECT, related_name="pickings_from",
    )
    location_dest = models.ForeignKey(
        StockLocation, on_delete=models.PROTECT, related_name="pickings_to",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name or str(self.id)

    def save(self, *args, **kwargs):
        if not self.name and self.picking_type_id:
            from inventory_apps.erp_base.models import SequenceCounter
            prefix = self.picking_type.sequence_prefix.rstrip("/") or "WH"
            self.name = SequenceCounter.next_sequence(prefix)
        super().save(*args, **kwargs)

    def action_confirm(self):
        if self.state == "draft":
            self.state = "confirmed"
            self.save(update_fields=["state"])
            self.move_lines.filter(state="draft").update(state="confirmed")

    def action_assign(self):
        if self.state in ("confirmed", "waiting"):
            self.state = "assigned"
            self.save(update_fields=["state"])

    def action_validate(self):
        from inventory_apps.erp_inventory.services import StockService
        StockService.validate_picking(self)

    def action_cancel(self):
        if self.state not in ("done", "cancel"):
            self.state = "cancel"
            self.save(update_fields=["state"])
            self.move_lines.exclude(state="done").update(state="cancel")


class StockMove(models.Model):
    STATE_CHOICES = [
        ("draft", "Draft"),
        ("cancel", "Cancelled"),
        ("waiting", "Waiting Another Move"),
        ("confirmed", "Confirmed"),
        ("assigned", "Available"),
        ("done", "Done"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    picking = models.ForeignKey(
        StockPicking, on_delete=models.CASCADE, null=True, blank=True,
        related_name="move_lines",
    )
    product = models.ForeignKey(
        "erp_base.ProductTemplate", on_delete=models.PROTECT, related_name="stock_moves",
    )
    lot = models.ForeignKey(
        StockLot, on_delete=models.SET_NULL, null=True, blank=True, related_name="moves",
    )
    description = models.CharField(max_length=255, blank=True)
    product_uom_qty = models.DecimalField(
        max_digits=18, decimal_places=4, default=Decimal("0.0000"),
        help_text="Demand quantity",
    )
    quantity_done = models.DecimalField(
        max_digits=18, decimal_places=4, default=Decimal("0.0000"),
        help_text="Actually done quantity",
    )
    location_src = models.ForeignKey(
        StockLocation, on_delete=models.PROTECT, related_name="moves_from",
    )
    location_dest = models.ForeignKey(
        StockLocation, on_delete=models.PROTECT, related_name="moves_to",
    )
    state = models.CharField(max_length=15, choices=STATE_CHOICES, default="draft")
    origin = models.CharField(max_length=255, blank=True)
    price_unit = models.DecimalField(
        max_digits=18, decimal_places=4, default=Decimal("0.0000"),
        help_text="Unit cost at time of move",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.product.name}: {self.quantity_done} ({self.state})"


class StockQuant(models.Model):
    """Current stock on-hand per location/product/lot."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(
        "erp_base.ProductTemplate", on_delete=models.CASCADE, related_name="quants",
    )
    location = models.ForeignKey(
        StockLocation, on_delete=models.CASCADE, related_name="quants",
    )
    lot = models.ForeignKey(
        StockLot, on_delete=models.SET_NULL, null=True, blank=True, related_name="quants",
    )
    quantity = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0.0000"))
    reserved_quantity = models.DecimalField(
        max_digits=18, decimal_places=4, default=Decimal("0.0000"),
    )
    inventory_date = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("product", "location", "lot")]
        ordering = ["product__name"]

    def __str__(self):
        return f"{self.product.name} @ {self.location.name}: {self.quantity}"

    @property
    def available_quantity(self) -> Decimal:
        return self.quantity - self.reserved_quantity


class StockInventoryAdjustment(models.Model):
    STATE_CHOICES = [("draft", "Draft"), ("validate", "Validated"), ("cancel", "Cancelled")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, blank=True)
    location = models.ForeignKey(
        StockLocation, on_delete=models.PROTECT, related_name="adjustments",
    )
    date = models.DateField(default=timezone.localdate)
    state = models.CharField(max_length=10, choices=STATE_CHOICES, default="draft")
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return self.name or f"INV/ADJ/{self.id}"


class StockInventoryAdjustmentLine(models.Model):
    adjustment = models.ForeignKey(
        StockInventoryAdjustment, on_delete=models.CASCADE, related_name="lines",
    )
    product = models.ForeignKey(
        "erp_base.ProductTemplate", on_delete=models.CASCADE, related_name="adjustment_lines",
    )
    lot = models.ForeignKey(
        StockLot, on_delete=models.SET_NULL, null=True, blank=True, related_name="adjustment_lines",
    )
    theoretical_qty = models.DecimalField(
        max_digits=18, decimal_places=4, default=Decimal("0.0000"),
    )
    inventory_qty = models.DecimalField(
        max_digits=18, decimal_places=4, default=Decimal("0.0000"),
    )
    difference_qty = models.DecimalField(
        max_digits=18, decimal_places=4, default=Decimal("0.0000"), editable=False,
    )

    def save(self, *args, **kwargs):
        self.difference_qty = self.inventory_qty - self.theoretical_qty
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.product.name}: {self.theoretical_qty} → {self.inventory_qty}"


class ReorderingRule(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(
        "erp_base.ProductTemplate", on_delete=models.CASCADE, related_name="reordering_rules",
    )
    location = models.ForeignKey(
        StockLocation, on_delete=models.CASCADE, related_name="reordering_rules",
    )
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.CASCADE, related_name="reordering_rules",
    )
    min_qty = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0.0000"))
    max_qty = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0.0000"))
    qty_multiple = models.DecimalField(
        max_digits=18, decimal_places=4, default=Decimal("1.0000"),
    )
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("product", "location")]
        ordering = ["product__name"]

    def __str__(self):
        return f"Reorder {self.product.name}: min={self.min_qty}, max={self.max_qty}"
