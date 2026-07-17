"""
erp_pos/services.py — POSService: process payment, close session, sync offline orders.
"""
from decimal import Decimal
from django.db import transaction
from django.utils import timezone


class POSService:

    @classmethod
    @transaction.atomic
    def process_payment(cls, pos_order):
        """Validate payment, update stock, optionally create invoice."""
        from inventory_apps.erp_pos.models import POSOrder, POSPayment
        from inventory_apps.erp_inventory.services import StockService
        from inventory_apps.erp_inventory.models import StockLocation, StockPickingType, StockPicking, StockMove

        if pos_order.state != "draft":
            raise ValueError("Order is not in draft state")

        pos_order.compute_totals()

        # Check if sufficient payment
        if pos_order.amount_paid < pos_order.amount_total:
            raise ValueError(
                f"Insufficient payment: need {pos_order.amount_total}, got {pos_order.amount_paid}"
            )

        # Reduce stock for storable products
        picking_type = StockPickingType.objects.filter(code="outgoing").first()
        if picking_type:
            storable_lines = [
                l for l in pos_order.lines.all()
                if l.product.product_type == "storable"
            ]
            if storable_lines:
                customer_loc = StockLocation.objects.filter(usage="customer").first()
                src_loc = picking_type.default_location_src
                if src_loc and customer_loc:
                    picking = StockPicking.objects.create(
                        picking_type=picking_type,
                        partner=pos_order.partner,
                        origin=pos_order.name,
                        location_src=src_loc,
                        location_dest=customer_loc,
                        state="confirmed",
                    )
                    for line in storable_lines:
                        StockMove.objects.create(
                            picking=picking,
                            product=line.product,
                            product_uom_qty=line.qty,
                            quantity_done=line.qty,
                            location_src=src_loc,
                            location_dest=customer_loc,
                            origin=pos_order.name,
                            state="confirmed",
                        )
                    StockService.validate_picking(picking)

        pos_order.state = "paid"
        pos_order.save(update_fields=["state"])
        return pos_order

    @classmethod
    @transaction.atomic
    def sync_offline_orders(cls, session, orders_data: list) -> list:
        """Sync orders sent from offline POS client. Returns created order IDs."""
        from inventory_apps.erp_pos.models import POSOrder, POSOrderLine, POSPayment, POSPaymentMethod
        from inventory_apps.erp_base.models import Partner, ProductTemplate

        created = []
        for data in orders_data:
            product_lines = data.get("lines", [])
            payments_data = data.get("payments", [])

            order = POSOrder.objects.create(
                session=session,
                partner_id=data.get("partner_id"),
                date_order=data.get("date_order") or timezone.now(),
                note=data.get("note", ""),
            )
            for line_data in product_lines:
                POSOrderLine.objects.create(
                    order=order,
                    product_id=line_data["product_id"],
                    qty=Decimal(str(line_data.get("qty", 1))),
                    price_unit=Decimal(str(line_data.get("price_unit", 0))),
                    discount=Decimal(str(line_data.get("discount", 0))),
                )
            for pay_data in payments_data:
                method = POSPaymentMethod.objects.filter(id=pay_data["method_id"]).first()
                if method:
                    POSPayment.objects.create(
                        pos_order=order,
                        payment_method=method,
                        amount=Decimal(str(pay_data.get("amount", 0))),
                        session=session,
                    )

            order.compute_totals()
            cls.process_payment(order)
            created.append(str(order.id))
        return created

    @classmethod
    @transaction.atomic
    def close_session(cls, session, closing_balance: Decimal = Decimal("0.00"), notes: str = ""):
        session.close_session(closing_balance, notes)
        return session

    @classmethod
    def get_session_summary(cls, session):
        from inventory_apps.erp_pos.models import POSPayment
        from django.db.models import Sum
        from inventory_apps.erp_accounting.models import AccountJournal

        orders = session.orders.filter(state__in=["paid", "done", "invoiced"])
        payments_by_method = (
            POSPayment.objects.filter(pos_order__session=session)
            .values("payment_method__name")
            .annotate(total=Sum("amount"))
        )

        return {
            "session_id": str(session.id),
            "session_name": session.name,
            "state": session.state,
            "opened_at": session.opened_at,
            "closed_at": session.closed_at,
            "order_count": orders.count(),
            "total_sales": orders.aggregate(t=Sum("amount_total"))["t"] or Decimal("0.00"),
            "cash_in": session.cash_register_balance_start,
            "cash_out": session.cash_register_balance_end,
            "cash_diff": session.cash_register_difference,
            "payments_by_method": list(payments_by_method),
        }
