"""
erp_inventory/services.py — StockService: validate pickings, update quants, adjust stock.
"""
from decimal import Decimal
from django.db import transaction
from django.utils import timezone


class StockService:

    @classmethod
    @transaction.atomic
    def validate_picking(cls, picking):
        """Mark all move lines done and update stock quants."""
        from inventory_apps.erp_inventory.models import StockMove, StockQuant
        if picking.state == "done":
            return picking

        for move in picking.move_lines.filter(state__in=("confirmed", "assigned", "draft")):
            qty = move.quantity_done if move.quantity_done > 0 else move.product_uom_qty
            move.quantity_done = qty
            move.state = "done"
            move.save(update_fields=["quantity_done", "state"])

            # Move stock from src → dest
            cls._update_quant(move.product, move.location_src, -qty, move.lot)
            cls._update_quant(move.product, move.location_dest, qty, move.lot)

        picking.state = "done"
        picking.date_done = timezone.now()
        picking.save(update_fields=["state", "date_done"])
        return picking

    @classmethod
    @transaction.atomic
    def _update_quant(cls, product, location, delta: Decimal, lot=None):
        from inventory_apps.erp_inventory.models import StockQuant
        quant, _ = StockQuant.objects.select_for_update().get_or_create(
            product=product,
            location=location,
            lot=lot,
            defaults={"quantity": Decimal("0.0000"), "reserved_quantity": Decimal("0.0000")},
        )
        quant.quantity = quant.quantity + delta
        quant.save(update_fields=["quantity", "updated_at"])

    @classmethod
    @transaction.atomic
    def apply_inventory_adjustment(cls, adjustment):
        """Apply inventory adjustment lines: create stock moves for differences."""
        from inventory_apps.erp_inventory.models import (
            StockInventoryAdjustment,
            StockQuant,
            StockMove,
            StockLocation,
        )
        if adjustment.state != "draft":
            raise ValueError("Adjustment already validated")

        StockLocation.objects.get_or_create(
            usage="inventory",
            defaults={"name": "Inventory adjustment"},
        )

        for line in adjustment.lines.all():
            diff = line.difference_qty
            if diff == Decimal("0.0000"):
                continue
            if diff > 0:
                cls._update_quant(line.product, adjustment.location, diff, line.lot)
            else:
                cls._update_quant(line.product, adjustment.location, diff, line.lot)

        adjustment.state = "validate"
        adjustment.save(update_fields=["state"])
        return adjustment

    @classmethod
    def get_stock_report(cls, warehouse=None):
        from inventory_apps.erp_inventory.models import StockQuant
        from inventory_apps.erp_base.models import ProductTemplate
        from django.db.models import Sum, F

        qs = StockQuant.objects.filter(location__usage="internal").select_related(
            "product", "location", "lot"
        )
        if warehouse:
            qs = qs.filter(location__warehouse=warehouse)

        return qs.values(
            product_id=F("product__id"),
            product_name=F("product__name"),
            location_name=F("location__complete_name"),
        ).annotate(
            qty_on_hand=Sum("quantity"),
            qty_reserved=Sum("reserved_quantity"),
        ).order_by("product_name")

    @classmethod
    def ensure_picking_type(cls, code):
        """Get the warehouse's picking type for `code`, self-healing it (and
        the supplier/customer virtual location it needs) into existence if
        missing — e.g. because those virtual locations didn't exist yet when
        the warehouse was first created, so _create_default_picking_types()
        silently skipped it.
        """
        from inventory_apps.erp_inventory.models import StockPickingType, StockLocation, Warehouse

        picking_type = StockPickingType.objects.filter(code=code).first()
        if picking_type:
            return picking_type

        warehouse = Warehouse.objects.filter(active=True).first()
        if not warehouse:
            raise ValueError("No warehouse configured")
        stock_loc = warehouse.lot_stock_location or StockLocation.objects.filter(
            warehouse=warehouse, name="Stock",
        ).first()
        if not stock_loc:
            raise ValueError(f"Warehouse '{warehouse.name}' is missing a Stock location")

        if code == "incoming":
            partner_loc, _ = StockLocation.objects.get_or_create(
                usage="supplier", defaults={"name": "Vendors"},
            )
            return StockPickingType.objects.create(
                name="Receipts", code="incoming", warehouse=warehouse,
                default_location_src=partner_loc, default_location_dest=stock_loc,
                sequence_prefix=f"{warehouse.short_name}/IN/",
            )
        if code == "outgoing":
            customer_loc, _ = StockLocation.objects.get_or_create(
                usage="customer", defaults={"name": "Customers"},
            )
            return StockPickingType.objects.create(
                name="Delivery Orders", code="outgoing", warehouse=warehouse,
                default_location_src=stock_loc, default_location_dest=customer_loc,
                sequence_prefix=f"{warehouse.short_name}/OUT/",
            )
        if code == "internal":
            return StockPickingType.objects.create(
                name="Internal Transfers", code="internal", warehouse=warehouse,
                default_location_src=stock_loc, default_location_dest=stock_loc,
                sequence_prefix=f"{warehouse.short_name}/INT/",
            )
        raise ValueError(f"Unknown picking type code '{code}'")

    @classmethod
    @transaction.atomic
    def create_receipt_from_po(cls, purchase_order):
        """Create a stock picking (receipt) from a confirmed purchase order."""
        from inventory_apps.erp_inventory.models import StockPicking, StockMove

        picking_type = cls.ensure_picking_type("incoming")
        partner_loc = picking_type.default_location_src
        dest_loc = picking_type.default_location_dest

        picking = StockPicking.objects.create(
            picking_type=picking_type,
            partner=purchase_order.partner,
            origin=purchase_order.name,
            location_src=partner_loc,
            location_dest=dest_loc,
            state="confirmed",
        )
        for line in purchase_order.lines.all():
            StockMove.objects.create(
                picking=picking,
                product=line.product,
                product_uom_qty=line.qty_to_receive,
                quantity_done=Decimal("0.0000"),
                location_src=partner_loc,
                location_dest=dest_loc,
                origin=purchase_order.name,
                price_unit=line.price_unit,
                state="confirmed",
            )
        purchase_order.receipt_count = (
            purchase_order.__class__.objects.filter(
                pk=purchase_order.pk
            ).values_list("receipt_count", flat=True).first() or 0
        ) + 1
        purchase_order.save(update_fields=["receipt_count"])
        return picking

    @classmethod
    @transaction.atomic
    def create_delivery_from_so(cls, sale_order):
        """Create a stock picking (delivery) from a confirmed sale order."""
        from inventory_apps.erp_inventory.models import StockPicking, StockMove

        picking_type = cls.ensure_picking_type("outgoing")
        customer_loc = picking_type.default_location_dest
        src_loc = picking_type.default_location_src

        picking = StockPicking.objects.create(
            picking_type=picking_type,
            partner=sale_order.partner,
            origin=sale_order.name,
            location_src=src_loc,
            location_dest=customer_loc,
            state="confirmed",
        )
        for line in sale_order.lines.all():
            StockMove.objects.create(
                picking=picking,
                product=line.product,
                product_uom_qty=line.product_uom_qty,
                quantity_done=Decimal("0.0000"),
                location_src=src_loc,
                location_dest=customer_loc,
                origin=sale_order.name,
                state="confirmed",
            )
        return picking
