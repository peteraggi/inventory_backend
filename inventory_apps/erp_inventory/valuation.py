"""
erp_inventory/valuation.py — stock ledger, FIFO cost layers and NRV write-downs.

Every quantity change goes through `post_movement`, which updates the quant,
appends a StockLedgerEntry and keeps the cost layers in step.

Cost layers exist for internal locations only. Virtual locations (vendor,
customer, scrap) are still ledgered, but they carry no value.
"""
from decimal import Decimal

from django.utils import timezone

from inventory_apps.erp_inventory.accounting import post_write_down

ZERO = Decimal("0")
UNIT_QUANT = Decimal("0.0001")


def standard_cost(product):
    return product.product_template.standard_price


def is_internal(location):
    return location.usage == "internal"


def post_movement(*, product, location, lot, delta, change_type,
                  reference_type="", reference_id=None, reference_name="", unit_cost=None, move=None):
    """
    Apply `delta` to the quant at (product, location, lot), append the ledger row and
    maintain cost layers. Returns the unit cost the movement was valued at.

    Outbound (delta < 0) consumes the oldest layers first (FIFO).
    Inbound (delta > 0) creates a layer at `unit_cost`, or the standard cost when none is given.
    """
    from inventory_apps.erp_inventory.models import StockLedgerEntry, StockQuant

    quant, _ = StockQuant.objects.select_for_update().get_or_create(
        product=product, location=location, lot=lot,
        defaults={"quantity": ZERO, "reserved_quantity": ZERO},
    )

    if delta < 0:
        cost = _consume_fifo(product, location, lot, -delta) if is_internal(location) else standard_cost(product)
    else:
        cost = unit_cost if unit_cost else standard_cost(product)
        if is_internal(location):
            _create_layer(product, location, lot, delta, cost, reference_name)

    quant.quantity = quant.quantity + delta
    quant.save(update_fields=["quantity", "updated_at"])

    StockLedgerEntry.objects.create(
        product=product,
        location=location,
        lot=lot,
        source_move=move,
        change_type=change_type,
        quantity_change=delta,
        resulting_quantity=quant.quantity,
        unit_cost=cost,
        reference_type=reference_type,
        reference_id=reference_id,
        reference_name=reference_name,
    )
    return cost


def _create_layer(product, location, lot, quantity, unit_cost, source_reference):
    from inventory_apps.erp_inventory.models import InventoryCostLayer
    return InventoryCostLayer.objects.create(
        product=product,
        location=location,
        lot=lot,
        received_at=timezone.now(),
        quantity_received=quantity,
        quantity_remaining=quantity,
        unit_cost=unit_cost,
        source_reference=source_reference,
    )


def _consume_fifo(product, location, lot, quantity):
    """Take `quantity` of one lot from its oldest layers. Returns the weighted-average unit cost."""
    from inventory_apps.erp_inventory.models import InventoryCostLayer

    remaining = quantity
    total_cost = ZERO
    layers = InventoryCostLayer.objects.select_for_update().filter(
        product=product, location=location, lot=lot, quantity_remaining__gt=0,
    ).order_by("received_at", "created_at", "id")

    for layer in layers:
        if remaining <= 0:
            break
        taken = min(layer.quantity_remaining, remaining)
        layer.quantity_remaining = layer.quantity_remaining - taken
        layer.save(update_fields=["quantity_remaining"])
        total_cost += taken * layer.unit_cost
        remaining -= taken

    # Stock that predates the ledger has no layers; value it at the standard cost.
    if remaining > 0:
        total_cost += remaining * standard_cost(product)

    return (total_cost / quantity).quantize(UNIT_QUANT)


def change_types_for_move(src, dest):
    """Ledger change types for the source and destination sides of one move."""
    if is_internal(src):
        out = "TRANSFER_OUT" if is_internal(dest) else "DELIVERY"
    else:
        out = "RECEIPT"
    if is_internal(dest):
        inn = "TRANSFER_IN" if is_internal(src) else "RECEIPT"
    else:
        inn = "DELIVERY"
    return out, inn


def run_nrv(warehouse=None, product=None):
    """
    Net realisable value write-down. Where the average cost of a product at a location
    exceeds its sale price, each layer is capped at the sale price and an
    InventoryNrvAdjustment records the loss. Re-running is a no-op once capped.
    """
    from inventory_apps.erp_inventory.models import InventoryCostLayer, InventoryNrvAdjustment
    from collections import defaultdict

    layers = InventoryCostLayer.objects.filter(
        quantity_remaining__gt=0, location__usage="internal",
    ).select_related("product__product_template", "location")
    if warehouse:
        layers = layers.filter(location__warehouse=warehouse)
    if product:
        layers = layers.filter(product=product)

    groups = defaultdict(list)
    for layer in layers:
        groups[(layer.product_id, layer.location_id, layer.lot_id)].append(layer)

    adjustments = []
    for group in groups.values():
        first = group[0]
        nrv = first.product.product_template.sale_price
        quantity = sum((layer.quantity_remaining for layer in group), ZERO)
        value = sum((layer.quantity_remaining * layer.unit_cost for layer in group), ZERO)
        average = (value / quantity).quantize(UNIT_QUANT)
        if average <= nrv:
            continue

        for layer in group:
            if layer.unit_cost > nrv:
                layer.unit_cost = nrv
                layer.save(update_fields=["unit_cost"])

        per_unit = average - nrv
        adjustment = InventoryNrvAdjustment.objects.create(
            product=first.product,
            location=first.location,
            lot=first.lot,
            quantity_basis=quantity,
            cost_per_unit=average,
            nrv_per_unit=nrv,
            per_unit_adjustment=per_unit,
            total_adjustment=(per_unit * quantity).quantize(UNIT_QUANT),
        )
        post_write_down(adjustment.total_adjustment, f"NRV {first.product.name} {first.location.complete_name}")
        adjustments.append(adjustment)
    return adjustments


def get_valuation(warehouse=None, product=None):
    """Quantity and value per (product, location) from the open cost layers."""
    from inventory_apps.erp_inventory.models import InventoryCostLayer
    from collections import defaultdict

    layers = InventoryCostLayer.objects.filter(
        quantity_remaining__gt=0, location__usage="internal",
    ).select_related("product__product_template", "location__warehouse")
    if warehouse:
        layers = layers.filter(location__warehouse=warehouse)
    if product:
        layers = layers.filter(product=product)

    totals = defaultdict(lambda: {"qty": ZERO, "value": ZERO, "product": None, "location": None, "lot": None})
    for layer in layers:
        key = (layer.product_id, layer.location_id, layer.lot_id)
        row = totals[key]
        row["qty"] += layer.quantity_remaining
        row["value"] += layer.quantity_remaining * layer.unit_cost
        row["product"] = layer.product
        row["location"] = layer.location
        row["lot"] = layer.lot

    rows = []
    for (product_id, location_id, lot_id), row in sorted(
        totals.items(), key=lambda item: (str(item[0][0]), str(item[0][1]), str(item[0][2])),
    ):
        qty = row["qty"]
        value = row["value"]
        rows.append({
            "product_id": str(product_id),
            "product_name": row["product"].name,
            "location_id": str(location_id),
            "location_name": row["location"].complete_name,
            "warehouse_name": row["location"].warehouse.name if row["location"].warehouse else "",
            "lot_name": row["lot"].name if row["lot"] else None,
            "quantity": qty,
            "value": value.quantize(UNIT_QUANT),
            "average_cost": (value / qty).quantize(UNIT_QUANT) if qty else ZERO,
        })
    return rows
