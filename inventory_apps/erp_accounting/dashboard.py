# inventory_apps/erp_accounting/dashboard.py

"""
DashboardService: headline sales figures for the dashboard.

Every figure is computed with grouped queries (one per source, not one per day or per
product), so the dashboard costs the same whatever the size of the catalogue.
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

ZERO = Decimal("0.00")
PAID_POS_STATES = ["paid", "done", "invoiced"]
CONFIRMED_SALE_STATES = ["sale", "done"]
LOW_STOCK_THRESHOLD = Decimal("5")


def _daily_totals(queryset, date_field, amount_field):
    rows = (
        queryset.annotate(day=TruncDate(date_field))
        .values("day")
        .annotate(total=Sum(amount_field))
        .order_by()
    )
    return {row["day"]: row["total"] or ZERO for row in rows}


def _sum_since(daily, start, end):
    return sum((total for day, total in daily.items() if start <= day <= end), ZERO)


class DashboardService:

    @classmethod
    def summary(cls, today=None):
        from inventory_apps.erp_inventory.models import StockQuant
        from inventory_apps.erp_pos.models import POSOrder, POSOrderLine
        from inventory_apps.erp_sales.models import SaleOrder
        from inventory_apps.erp_base.models import ProductVariant

        today = today or timezone.localdate()
        week_ago = today - timedelta(days=6)
        month_ago = today - timedelta(days=29)
        trend_start = today - timedelta(days=13)

        pos_orders = POSOrder.objects.filter(state__in=PAID_POS_STATES, date_order__date__gte=month_ago)
        sale_orders = SaleOrder.objects.filter(state__in=CONFIRMED_SALE_STATES, date_order__date__gte=month_ago)
        pos_daily = _daily_totals(pos_orders, "date_order", "amount_total")
        sale_daily = _daily_totals(sale_orders, "date_order", "amount_total")
        revenue_daily = {
            day: pos_daily.get(day, ZERO) + sale_daily.get(day, ZERO)
            for day in set(pos_daily) | set(sale_daily)
        }

        order_count = (
            pos_orders.filter(date_order__date=today).count()
            + sale_orders.filter(date_order__date=today).count()
        )

        sold_lines = POSOrderLine.objects.filter(
            order__state__in=PAID_POS_STATES, order__date_order__date__gte=month_ago,
        )
        top_today = (
            sold_lines.filter(order__date_order__date=today)
            .values("product__product_template__name")
            .annotate(total_qty=Sum("qty"))
            .order_by("-total_qty")
            .first()
        )
        top_products = [
            {"name": row["product__product_template__name"], "qty": row["total_qty"]}
            for row in sold_lines.values("product__product_template__name")
            .annotate(total_qty=Sum("qty"))
            .order_by("-total_qty")[:5]
        ]

        # Low stock: active storable products whose on-hand quantity is at or below the threshold.
        on_hand = {
            row["product_id"]: row["total"] or ZERO
            for row in StockQuant.objects.filter(location__usage="internal")
            .values("product_id")
            .annotate(total=Sum("quantity"))
        }
        storable_variant_ids = ProductVariant.objects.filter(
            active=True, product_template__product_type="storable",
        ).values_list("id", flat=True)
        low_stock_count = sum(1 for variant_id in storable_variant_ids if on_hand.get(variant_id, ZERO) <= LOW_STOCK_THRESHOLD)

        sales_trend = [
            {"date": (trend_start + timedelta(days=i)).isoformat(),
             "total": revenue_daily.get(trend_start + timedelta(days=i), ZERO)}
            for i in range(14)
        ]

        pos_month = _sum_since(pos_daily, month_ago, today)
        sales_month = _sum_since(sale_daily, month_ago, today)

        return {
            "today_sales": revenue_daily.get(today, ZERO),
            "week_sales": _sum_since(revenue_daily, week_ago, today),
            "month_sales": _sum_since(revenue_daily, month_ago, today),
            "order_count": order_count,
            "top_product": top_today["product__product_template__name"] if top_today else "N/A",
            "low_stock_count": low_stock_count,
            "sales_trend": sales_trend,
            "top_products": top_products,
            "channel_breakdown": [
                {"channel": "POS", "total": pos_month},
                {"channel": "Sales Orders", "total": sales_month},
            ],
        }
