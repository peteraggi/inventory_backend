"""
erp_inventory/services.py — StockService: validate pickings, update quants, adjust stock.
"""
from decimal import Decimal
from django.db import transaction
from django.utils import timezone

from inventory_apps.erp_inventory.accounting import (
    post_adjustment_value, post_scrap_value, post_transfer_value,
)
from inventory_apps.erp_inventory.valuation import (
    change_types_for_move, is_internal, post_movement,
)


class StockService:

    @classmethod
    def _check_available(cls, move, qty):
        """
        Refuse to take more than is on hand from an internal location. The quant row is
        locked until the surrounding transaction ends, so two deliveries cannot both
        pass this check against the same stock.
        """
        from inventory_apps.erp_inventory.models import StockQuant
        quant = StockQuant.objects.select_for_update().filter(
            product=move.product, location=move.location_src, lot=move.lot,
        ).first()
        available = quant.quantity if quant else Decimal("0")
        if available < qty:
            raise ValueError(
                f"Not enough stock of {move.product.name} at {move.location_src.complete_name}: "
                f"{available} available, {qty} needed."
            )

    @classmethod
    @transaction.atomic
    def validate_picking(cls, picking, allow_negative=False):
        """
        Mark all move lines done, post them to stock and the ledger, and value them.

        Stock leaving an internal location must be on hand unless `allow_negative` is set.
        POS sales pass it, because an offline sale has already happened when it syncs.
        """
        if picking.state == "done":
            return picking

        now = timezone.now()
        for move in picking.move_lines.filter(state__in=("confirmed", "assigned", "draft")):
            qty = move.quantity_done if move.quantity_done > 0 else move.product_uom_qty
            if not allow_negative and is_internal(move.location_src):
                cls._check_available(move, qty)
            move.quantity_done = qty
            move.state = "done"
            move.date_done = now
            move.save(update_fields=["quantity_done", "state", "date_done"])

            out_type, in_type = change_types_for_move(move.location_src, move.location_dest)
            reference = {
                "reference_type": "TRANSFER",
                "reference_id": picking.id,
                "reference_name": picking.name,
            }
            cost = post_movement(
                product=move.product, location=move.location_src, lot=move.lot,
                delta=-qty, change_type=out_type, move=move, **reference,
            )
            # Stock leaving an internal location carries its cost into the destination;
            # stock arriving from outside is valued at the move's own price.
            inbound_cost = cost if is_internal(move.location_src) else (move.price_unit or None)
            received_cost = post_movement(
                product=move.product, location=move.location_dest, lot=move.lot,
                delta=qty, change_type=in_type, unit_cost=inbound_cost, move=move, **reference,
            )
            value = qty * (cost if is_internal(move.location_src) else received_cost)
            post_transfer_value(move.location_src, move.location_dest, value, picking.name)

        picking.state = "done"
        picking.date_done = now
        picking.save(update_fields=["state", "date_done"])
        return picking

    @classmethod
    @transaction.atomic
    def apply_inventory_adjustment(cls, adjustment):
        """Apply inventory adjustment lines by posting each counted difference to its quant."""
        if adjustment.state != "draft":
            raise ValueError("Adjustment already validated")

        for line in adjustment.lines.all():
            diff = line.difference_qty
            if diff == Decimal("0.0000"):
                continue
            cost = post_movement(
                product=line.product, location=adjustment.location, lot=line.lot, delta=diff,
                change_type="ADJUSTMENT", reference_type="ADJUSTMENT",
                reference_id=adjustment.id, reference_name=adjustment.name,
            )
            post_adjustment_value(diff * cost, adjustment.name)

        adjustment.state = "validate"
        adjustment.save(update_fields=["state"])
        return adjustment

    @classmethod
    @transaction.atomic
    def apply_quant_counts(cls, counts):
        """
        Set counted quantities on existing quants.

        `counts` is an iterable of (quant_id, inventory_quantity). Each difference is
        posted through post_movement, so the ledger and cost layers stay consistent.
        """
        from inventory_apps.erp_inventory.models import StockQuant

        applied = 0
        for quant_id, inventory_quantity in counts:
            quant = StockQuant.objects.select_related("product", "location", "lot").filter(
                pk=quant_id,
            ).first()
            if quant is None:
                raise ValueError(f"Stock quant '{quant_id}' does not exist")
            diff = Decimal(inventory_quantity) - quant.quantity
            if diff == Decimal("0.0000"):
                continue
            cost = post_movement(
                product=quant.product, location=quant.location, lot=quant.lot, delta=diff,
                change_type="STOCK_TAKE", reference_type="STOCK_TAKE",
            )
            post_adjustment_value(diff * cost, f"Physical count {quant.location.complete_name}")
            applied += 1
        return applied

    @classmethod
    def get_stock_report(cls, warehouse=None):
        from inventory_apps.erp_inventory.models import StockQuant
        from django.db.models import Sum, F

        qs = StockQuant.objects.filter(location__usage="internal").select_related(
            "product__product_template", "location", "lot"
        )
        if warehouse:
            qs = qs.filter(location__warehouse=warehouse)

        return qs.values(
            product_id=F("product__id"),
            product_name=F("product__product_template__name"),
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

    # ─── Helpers shared by returns, scrap, forecast and replenishment ───────

    ACTIVE_MOVE_STATES = ("draft", "waiting", "confirmed", "assigned")
    REVERSE_PICKING_CODE = {"incoming": "outgoing", "outgoing": "incoming", "internal": "internal"}

    @classmethod
    def default_stock_location(cls):
        """Stock location of the first active warehouse; used when a request omits one."""
        from inventory_apps.erp_inventory.models import Warehouse
        warehouse = Warehouse.objects.filter(active=True).select_related("lot_stock_location").first()
        if warehouse is None or warehouse.lot_stock_location is None:
            raise ValueError("No warehouse with a stock location is configured")
        return warehouse.lot_stock_location

    @classmethod
    def scrap_location(cls):
        from inventory_apps.erp_inventory.models import StockLocation
        location, _ = StockLocation.objects.get_or_create(
            usage="inventory", name="Scrap", defaults={"notes": "Scrapped stock"},
        )
        return location

    @classmethod
    def quantity_at(cls, product, location, lot=None):
        from inventory_apps.erp_inventory.models import StockQuant
        quant = StockQuant.objects.filter(product=product, location=location, lot=lot).first()
        return quant.quantity if quant else Decimal("0.0000")

    @classmethod
    def forecast_qty(cls, product, location):
        """On hand + incoming - outgoing for one product at one location."""
        from inventory_apps.erp_inventory.models import StockMove, StockQuant
        from django.db.models import Sum

        on_hand = StockQuant.objects.filter(product=product, location=location).aggregate(
            total=Sum("quantity"))["total"] or Decimal("0")
        incoming = StockMove.objects.filter(
            product=product, location_dest=location, state__in=cls.ACTIVE_MOVE_STATES,
        ).aggregate(total=Sum("product_uom_qty"))["total"] or Decimal("0")
        outgoing = StockMove.objects.filter(
            product=product, location_src=location, state__in=cls.ACTIVE_MOVE_STATES,
        ).aggregate(total=Sum("product_uom_qty"))["total"] or Decimal("0")
        return on_hand + incoming - outgoing

    # ─── Return ─────────────────────────────────────────────────────────────

    @classmethod
    @transaction.atomic
    def create_return_picking(cls, picking):
        """Create a draft reverse transfer of a done transfer (goods travel back the other way)."""
        from inventory_apps.erp_inventory.models import StockPicking, StockPickingType, StockMove

        if picking.state != "done":
            raise ValueError("Only done transfers can be returned")
        warehouse = picking.picking_type.warehouse
        reverse_type = StockPickingType.objects.filter(
            warehouse=warehouse,
            code=cls.REVERSE_PICKING_CODE[picking.picking_type.code],
            active=True,
        ).first() if warehouse else None
        if reverse_type is None:
            raise ValueError("No operation type is configured for this return")

        returned = StockPicking.objects.create(
            picking_type=reverse_type,
            return_of=picking,
            partner=picking.partner,
            origin=f"Return of {picking.name}",
            location_src=picking.location_dest,
            location_dest=picking.location_src,
            state="confirmed",
        )
        for move in picking.move_lines.all():
            StockMove.objects.create(
                picking=returned,
                product=move.product,
                lot=move.lot,
                product_uom_qty=move.quantity_done or move.product_uom_qty,
                location_src=returned.location_src,
                location_dest=returned.location_dest,
                origin=returned.origin,
                state="confirmed",
            )
        return returned

    # ─── Scrap ──────────────────────────────────────────────────────────────

    @classmethod
    @transaction.atomic
    def validate_scrap(cls, scrap):
        """Move the scrapped quantity from its location to the scrap location."""
        if scrap.state != "draft":
            raise ValueError("Scrap order already processed")
        available = cls.quantity_at(scrap.product, scrap.location, scrap.lot)
        if available < scrap.quantity:
            raise ValueError(f"Insufficient stock: {available} available, {scrap.quantity} requested")

        reference = {
            "change_type": "SCRAP",
            "reference_type": "SCRAP",
            "reference_id": scrap.id,
            "reference_name": scrap.name,
        }
        cost = post_movement(
            product=scrap.product, location=scrap.location, lot=scrap.lot,
            delta=-scrap.quantity, **reference,
        )
        post_movement(
            product=scrap.product, location=scrap.scrap_location, lot=scrap.lot,
            delta=scrap.quantity, unit_cost=cost, **reference,
        )
        post_scrap_value(scrap.quantity * cost, scrap.name)
        scrap.state = "done"
        scrap.save(update_fields=["state", "updated_at"])
        return scrap

    # ─── Forecast ───────────────────────────────────────────────────────────

    @classmethod
    def get_forecast(cls, warehouse=None, product=None):
        """One row per (product, internal location): on hand, incoming, outgoing, forecasted."""
        from inventory_apps.erp_inventory.models import StockMove, StockQuant, StockLocation
        from inventory_apps.erp_base.models import ProductVariant
        from django.db.models import Sum

        quants = StockQuant.objects.filter(location__usage="internal")
        moves = StockMove.objects.filter(state__in=cls.ACTIVE_MOVE_STATES)
        if warehouse:
            quants = quants.filter(location__warehouse=warehouse)
        if product:
            quants = quants.filter(product=product)
            moves = moves.filter(product=product)

        on_hand = {
            (row["product_id"], row["location_id"]): row["total"]
            for row in quants.values("product_id", "location_id").annotate(total=Sum("quantity"))
        }
        incoming = {
            (row["product_id"], row["location_dest_id"]): row["total"]
            for row in moves.filter(location_dest__usage="internal").values(
                "product_id", "location_dest_id").annotate(total=Sum("product_uom_qty"))
        }
        outgoing = {
            (row["product_id"], row["location_src_id"]): row["total"]
            for row in moves.filter(location_src__usage="internal").values(
                "product_id", "location_src_id").annotate(total=Sum("product_uom_qty"))
        }

        keys = set(on_hand) | set(incoming) | set(outgoing)
        product_ids = {k[0] for k in keys}
        location_ids = {k[1] for k in keys}
        products = ProductVariant.objects.select_related("product_template").in_bulk(product_ids)
        locations = StockLocation.objects.select_related("warehouse").in_bulk(location_ids)

        rows = []
        for product_id, location_id in sorted(keys, key=lambda k: (str(k[0]), str(k[1]))):
            product_obj = products[product_id]
            location = locations[location_id]
            qty_on_hand = on_hand.get((product_id, location_id), Decimal("0"))
            qty_in = incoming.get((product_id, location_id), Decimal("0"))
            qty_out = outgoing.get((product_id, location_id), Decimal("0"))
            rows.append({
                "product_id": str(product_id),
                "product_name": product_obj.name,
                "location_id": str(location_id),
                "location_name": location.complete_name,
                "warehouse_name": location.warehouse.name if location.warehouse else "",
                "qty_on_hand": qty_on_hand,
                "incoming_qty": qty_in,
                "outgoing_qty": qty_out,
                "forecasted_qty": qty_on_hand + qty_in - qty_out,
            })
        return rows

    # ─── Replenishment ──────────────────────────────────────────────────────

    @classmethod
    @transaction.atomic
    def run_replenishment(cls):
        """
        For each active reordering rule whose forecast is below its minimum, create a
        confirmed receipt that tops the location up to the maximum, rounded to qty_multiple.
        """
        from inventory_apps.erp_inventory.models import ReorderingRule, StockPicking, StockPickingType, StockMove
        from math import ceil

        created = []
        rules = ReorderingRule.objects.filter(active=True).select_related("product", "location", "warehouse")
        for rule in rules:
            forecast = cls.forecast_qty(rule.product, rule.location)
            if forecast >= rule.min_qty:
                continue
            needed = rule.max_qty - forecast
            multiple = rule.qty_multiple if rule.qty_multiple > 0 else Decimal("1")
            if needed <= 0:
                continue
            needed = Decimal(ceil(needed / multiple)) * multiple

            receipt_type = StockPickingType.objects.filter(
                warehouse=rule.warehouse, code="incoming", active=True,
            ).first()
            if receipt_type is None or receipt_type.default_location_src is None:
                raise ValueError(f"Warehouse '{rule.warehouse.name}' has no receipt operation type")
            vendor = receipt_type.default_location_src

            picking = StockPicking.objects.create(
                picking_type=receipt_type,
                origin="Replenishment",
                location_src=vendor,
                location_dest=rule.location,
                state="confirmed",
            )
            StockMove.objects.create(
                picking=picking,
                product=rule.product,
                product_uom_qty=needed,
                location_src=vendor,
                location_dest=rule.location,
                origin="Replenishment",
                state="confirmed",
            )
            created.append(picking)
        return created
