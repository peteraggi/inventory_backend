from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend

from inventory_apps.erp_inventory.models import (
    Warehouse, StockLocation, StockPickingType, StockLot,
    StockPicking, StockMove, StockQuant,
    StockInventoryAdjustment, ReorderingRule,
)
from inventory_apps.erp_inventory.serializers import (
    WarehouseSerializer, StockLocationSerializer, StockPickingTypeSerializer,
    StockLotSerializer, StockPickingSerializer, StockPickingCreateSerializer,
    StockMoveSerializer, StockQuantSerializer, InventoryAdjustmentSerializer,
    ReorderingRuleSerializer,
)
from inventory_apps.erp_inventory.services import StockService


class WarehouseViewSet(viewsets.ModelViewSet):
    queryset = Warehouse.objects.filter(active=True).prefetch_related("locations")
    serializer_class = WarehouseSerializer
    permission_classes = [IsAuthenticated]


class StockLocationViewSet(viewsets.ModelViewSet):
    queryset = StockLocation.objects.filter(active=True)
    serializer_class = StockLocationSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["name", "complete_name"]
    filterset_fields = ["usage", "warehouse", "is_scrap"]


class StockPickingTypeViewSet(viewsets.ModelViewSet):
    queryset = StockPickingType.objects.filter(active=True)
    serializer_class = StockPickingTypeSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["code", "warehouse"]


class StockLotViewSet(viewsets.ModelViewSet):
    queryset = StockLot.objects.filter(active=True).select_related("product__product_template")
    serializer_class = StockLotSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["name", "ref"]
    filterset_fields = ["product"]


class StockPickingViewSet(viewsets.ModelViewSet):
    queryset = StockPicking.objects.all().select_related(
        "picking_type", "partner", "location_src", "location_dest"
    ).prefetch_related("move_lines")
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["name", "origin"]
    filterset_fields = ["state", "picking_type", "picking_type__code", "origin"]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return StockPickingCreateSerializer
        return StockPickingSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        picking = serializer.save()
        return Response(StockPickingSerializer(picking).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        picking = self.get_object()
        picking.action_confirm()
        return Response(StockPickingSerializer(picking).data)

    @action(detail=True, methods=["post"])
    def validate(self, request, pk=None):
        picking = self.get_object()
        try:
            StockService.validate_picking(picking)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(StockPickingSerializer(picking).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        picking = self.get_object()
        picking.action_cancel()
        return Response(StockPickingSerializer(picking).data)


class StockMoveViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = StockMove.objects.all().select_related(
        "product__product_template", "location_src", "location_dest", "picking",
    )
    serializer_class = StockMoveSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["state", "product", "picking"]


class StockQuantViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = StockQuant.objects.filter(
        location__usage="internal"
    ).select_related("product__product_template", "location", "lot")
    serializer_class = StockQuantSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["product", "product__product_template", "location", "lot"]
    search_fields = ["product__product_template__name"]

    @action(detail=False, url_path="report")
    def report(self, request):
        warehouse_id = request.query_params.get("warehouse")
        warehouse = None
        if warehouse_id:
            from inventory_apps.erp_inventory.models import Warehouse as W
            try:
                warehouse = W.objects.get(pk=warehouse_id)
            except W.DoesNotExist:
                pass
        data = list(StockService.get_stock_report(warehouse))
        return Response(data)


class InventoryAdjustmentViewSet(viewsets.ModelViewSet):
    queryset = StockInventoryAdjustment.objects.all().prefetch_related("lines__product__product_template")
    serializer_class = InventoryAdjustmentSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["state"]

    @action(detail=True, methods=["post"])
    def validate(self, request, pk=None):
        adj = self.get_object()
        try:
            StockService.apply_inventory_adjustment(adj)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(InventoryAdjustmentSerializer(adj).data)


class ReorderingRuleViewSet(viewsets.ModelViewSet):
    queryset = ReorderingRule.objects.filter(active=True).select_related("product__product_template", "location", "warehouse")
    serializer_class = ReorderingRuleSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["product", "warehouse"]


class InventoryDashboardView(APIView):
    """Aggregates for the Inventory dashboard (OAS-style overview): stock
    stats, open operations per type, 30-day stock movement, stock value by
    category, and recent/top products and transfers."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from datetime import timedelta
        from decimal import Decimal
        from django.db.models import DecimalField, ExpressionWrapper, F, Q, Sum, Value
        from django.db.models.functions import Coalesce, TruncDate
        from django.utils import timezone
        from inventory_apps.erp_base.models import ProductTemplate

        now = timezone.now()
        start = timezone.localdate() - timedelta(days=29)
        zero = Decimal("0")
        money = DecimalField(max_digits=20, decimal_places=2)
        cost = ExpressionWrapper(F("quantity") * F("product__product_template__standard_price"), output_field=money)

        internal_quants = StockQuant.objects.filter(location__usage="internal")
        templates = ProductTemplate.objects.filter(active=True)
        on_hand = Coalesce(
            Sum("variants__quants__quantity", filter=Q(variants__quants__location__usage="internal")),
            zero,
            output_field=DecimalField(max_digits=18, decimal_places=4),
        )
        storable = templates.filter(product_type="storable").annotate(on_hand=on_hand)

        open_pickings = StockPicking.objects.filter(state__in=("confirmed", "waiting", "assigned"))
        operations = {}
        for code in ("incoming", "outgoing", "internal"):
            qs = open_pickings.filter(picking_type__code=code)
            operations[code] = {
                "ready": qs.filter(state="assigned").count(),
                "waiting": qs.exclude(state="assigned").count(),
                "late": qs.filter(scheduled_date__lt=now).count(),
            }

        done_moves = StockMove.objects.filter(state="done", updated_at__date__gte=start)
        incoming = Q(location_dest__usage="internal") & ~Q(location_src__usage="internal")
        outgoing = Q(location_src__usage="internal") & ~Q(location_dest__usage="internal")
        by_day = {
            row["day"]: row
            for row in done_moves.annotate(day=TruncDate("updated_at"))
            .values("day")
            .annotate(
                incoming=Coalesce(Sum("quantity_done", filter=incoming), zero),
                outgoing=Coalesce(Sum("quantity_done", filter=outgoing), zero),
            )
        }
        movements = []
        for i in range(30):
            day = start + timedelta(days=i)
            row = by_day.get(day, {})
            movements.append({
                "date": day.isoformat(),
                "incoming": row.get("incoming", zero),
                "outgoing": row.get("outgoing", zero),
            })

        return Response({
            "stats": {
                "product_count": templates.count(),
                "storable_count": storable.count(),
                "stock_value": internal_quants.aggregate(v=Coalesce(Sum(cost), zero, output_field=money))["v"],
                "stock_qty": internal_quants.aggregate(q=Coalesce(Sum("quantity"), zero))["q"],
                "low_stock_count": storable.filter(on_hand__gt=0, on_hand__lte=5).count(),
                "out_of_stock_count": storable.filter(on_hand__lte=0).count(),
                "warehouse_count": Warehouse.objects.filter(active=True).count(),
                "open_transfers": open_pickings.count(),
                "late_transfers": open_pickings.filter(scheduled_date__lt=now).count(),
            },
            "operations": operations,
            "stock_movements": movements,
            "category_values": list(
                internal_quants.values(category=Coalesce(F("product__product_template__category__name"), Value("Uncategorized")))
                .annotate(value=Coalesce(Sum(cost), zero, output_field=money), qty=Sum("quantity"))
                .order_by("-value")[:8]
            ),
            "recent_products": [
                {
                    "id": p.id, "name": p.name, "sale_price": p.sale_price,
                    "on_hand": p.on_hand, "product_type": p.product_type, "created_at": p.created_at,
                }
                for p in templates.annotate(on_hand=on_hand).order_by("-created_at")[:6]
            ],
            "top_products": list(
                internal_quants.values(
                    template_id=F("product__product_template__id"),
                    name=F("product__product_template__name"),
                )
                .annotate(qty=Sum("quantity"), value=Coalesce(Sum(cost), zero, output_field=money))
                .order_by("-value")[:6]
            ),
            "recent_transfers": [
                {
                    "id": p.id, "name": p.name, "state": p.state,
                    "type": p.picking_type.code if p.picking_type_id else "",
                    "partner": p.partner.name if p.partner_id else "",
                    "scheduled_date": p.scheduled_date, "origin": p.origin,
                }
                for p in StockPicking.objects.select_related("picking_type", "partner").order_by("-created_at")[:6]
            ],
        })
