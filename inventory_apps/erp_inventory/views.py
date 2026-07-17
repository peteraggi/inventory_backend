from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
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
    queryset = StockLot.objects.filter(active=True).select_related("product")
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
        "product", "location_src", "location_dest", "picking",
    )
    serializer_class = StockMoveSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["state", "product", "picking"]


class StockQuantViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = StockQuant.objects.filter(
        location__usage="internal"
    ).select_related("product", "location", "lot")
    serializer_class = StockQuantSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["product", "location", "lot"]
    search_fields = ["product__name"]

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
    queryset = StockInventoryAdjustment.objects.all().prefetch_related("lines__product")
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
    queryset = ReorderingRule.objects.filter(active=True).select_related("product", "location", "warehouse")
    serializer_class = ReorderingRuleSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["product", "warehouse"]
