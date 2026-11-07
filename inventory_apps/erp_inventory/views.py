# inventory_apps/erp_inventory/views.py

from decimal import Decimal

from rest_framework import mixins, viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from inventory_apps.authentication.permissions import HasErpPermission
from inventory_core.exceptions import inventory_exception_handler
from inventory_apps.erp_inventory.models import (
    Warehouse, StockLocation, StockPickingType, StockLot,
    StockPicking, StockMove, StockQuant,
    StockInventoryAdjustment, ReorderingRule, ScrapOrder, StockLedgerEntry, InventoryNrvAdjustment,
)
from inventory_apps.erp_inventory.serializers import (
    WarehouseSerializer, StockLocationSerializer, StockPickingTypeSerializer,
    StockLotSerializer, StockPickingSerializer, StockPickingCreateSerializer,
    StockMoveSerializer, StockQuantSerializer, InventoryAdjustmentSerializer,
    ReorderingRuleSerializer, QuantCountSerializer, ScrapOrderSerializer,
    StockLedgerEntrySerializer, InventoryNrvAdjustmentSerializer,
)
from inventory_apps.erp_inventory.services import StockService
from inventory_apps.erp_inventory import valuation
from inventory_apps.notifications.models import NotificationType
from inventory_apps.notifications.services import NotificationService


class InventoryErrorMixin:
    """Every inventory endpoint returns {"success": False, "error": "..."} on failure."""

    # Workflow actions change stock or accounts, so they need "update" rather than "create".
    erp_action_map = {
        "validate": "update",
        "confirm": "update",
        "cancel": "update",
        "return_picking": "update",
        "apply": "update",
        "replenish": "update",
    }

    def get_exception_handler(self):
        return inventory_exception_handler


class WarehouseViewSet(InventoryErrorMixin, viewsets.ModelViewSet):
    queryset = Warehouse.objects.filter(active=True).prefetch_related("locations")
    serializer_class = WarehouseSerializer
    permission_classes = [IsAuthenticated, HasErpPermission]
    erp_resource = "inventory"


class StockLocationViewSet(InventoryErrorMixin, viewsets.ModelViewSet):
    queryset = StockLocation.objects.filter(active=True)
    serializer_class = StockLocationSerializer
    permission_classes = [IsAuthenticated, HasErpPermission]
    erp_resource = "inventory"
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["name", "complete_name"]
    filterset_fields = ["usage", "warehouse", "is_scrap"]


class StockPickingTypeViewSet(InventoryErrorMixin, viewsets.ModelViewSet):
    """Operation types (Receipts, Delivery Orders, Internal Transfers) per warehouse."""
    queryset = StockPickingType.objects.filter(active=True)
    serializer_class = StockPickingTypeSerializer
    permission_classes = [IsAuthenticated, HasErpPermission]
    erp_resource = "inventory"
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["name"]
    filterset_fields = ["code", "warehouse"]


class StockLotViewSet(InventoryErrorMixin, viewsets.ModelViewSet):
    queryset = StockLot.objects.filter(active=True).select_related("product__product_template")
    serializer_class = StockLotSerializer
    permission_classes = [IsAuthenticated, HasErpPermission]
    erp_resource = "inventory"
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["name", "ref"]
    filterset_fields = ["product"]


class StockPickingViewSet(InventoryErrorMixin, viewsets.ModelViewSet):
    """
    Transfers. Workflow actions: confirm, validate, cancel.
    validate applies stock moves to quants; its errors come back as {"error": ...}.
    """
    queryset = StockPicking.objects.all().select_related(
        "picking_type", "partner", "location_src", "location_dest"
    ).prefetch_related("move_lines")
    permission_classes = [IsAuthenticated, HasErpPermission]
    erp_resource = "inventory"
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["name", "origin"]
    filterset_fields = ["state", "picking_type", "picking_type__code", "origin"]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.query_params.get("is_return") == "true":
            queryset = queryset.filter(return_of__isnull=False)
        return queryset

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
        except ValueError as e:
            raise ValidationError(str(e))
        NotificationService.notify_picking_validated(request.user, picking)
        return Response(StockPickingSerializer(picking).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        picking = self.get_object()
        picking.action_cancel()
        NotificationService.notify_picking_cancelled(request.user, picking)
        return Response(StockPickingSerializer(picking).data)

    @action(detail=True, methods=["post"], url_path="return")
    def return_picking(self, request, pk=None):
        """Create a draft reverse transfer for a done transfer."""
        picking = self.get_object()
        try:
            returned = StockService.create_return_picking(picking)
        except ValueError as e:
            raise ValidationError(str(e))
        return Response(StockPickingSerializer(returned).data, status=status.HTTP_201_CREATED)


class StockMoveViewSet(InventoryErrorMixin, viewsets.ReadOnlyModelViewSet):
    """Stock move lines — read-only; moves are created through transfers and adjustments."""
    queryset = StockMove.objects.all().select_related(
        "product__product_template", "location_src", "location_dest", "picking", "lot",
    )
    serializer_class = StockMoveSerializer
    permission_classes = [IsAuthenticated, HasErpPermission]
    erp_resource = "inventory"
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["origin", "picking__name", "product__product_template__name"]
    filterset_fields = ["state", "product", "picking"]

    def get_queryset(self):
        queryset = super().get_queryset()
        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")
        if date_from:
            queryset = queryset.filter(updated_at__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(updated_at__date__lte=date_to)
        return queryset


class StockQuantViewSet(InventoryErrorMixin, viewsets.ReadOnlyModelViewSet):
    """Current on-hand stock per product, location and lot (internal locations only)."""
    queryset = StockQuant.objects.filter(
        location__usage="internal"
    ).select_related("product__product_template", "location", "lot")
    serializer_class = StockQuantSerializer
    permission_classes = [IsAuthenticated, HasErpPermission]
    erp_resource = "inventory"
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["product", "product__product_template", "location", "lot"]
    search_fields = ["product__product_template__name"]

    @action(detail=False, url_path="report")
    def report(self, request):
        warehouse_id = request.query_params.get("warehouse")
        warehouse = None
        if warehouse_id:
            warehouse = Warehouse.objects.filter(pk=warehouse_id).first()
        data = list(StockService.get_stock_report(warehouse))
        return Response(data)

    @action(detail=False, methods=["post"], url_path="apply")
    def apply(self, request):
        """
        Physical count: POST {"quants": [{"quant_id": "...", "inventory_quantity": 5}]}
        Each counted difference is posted to stock as a quant update.
        """
        serializer = QuantCountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        counts = [
            (line["quant_id"], line["inventory_quantity"])
            for line in serializer.validated_data["quants"]
        ]
        try:
            applied = StockService.apply_quant_counts(counts)
        except ValueError as e:
            raise ValidationError(str(e))
        NotificationService.create_notification(
            user=request.user,
            notification_type=NotificationType.STOCK_COUNT_APPLIED,
            title="Physical count applied",
            message=f"{applied} stock line(s) were updated from the physical count.",
            metadata={"applied": applied},
        )
        return Response({"success": True, "applied": applied})


class InventoryAdjustmentViewSet(InventoryErrorMixin, viewsets.ModelViewSet):
    queryset = StockInventoryAdjustment.objects.all().prefetch_related("lines__product__product_template")
    serializer_class = InventoryAdjustmentSerializer
    permission_classes = [IsAuthenticated, HasErpPermission]
    erp_resource = "inventory"
    filterset_fields = ["state"]

    @action(detail=True, methods=["post"])
    def validate(self, request, pk=None):
        adjustment = self.get_object()
        try:
            StockService.apply_inventory_adjustment(adjustment)
        except ValueError as e:
            raise ValidationError(str(e))
        NotificationService.notify_adjustment_validated(request.user, adjustment)
        return Response(InventoryAdjustmentSerializer(adjustment).data)


class ReorderingRuleViewSet(InventoryErrorMixin, viewsets.ModelViewSet):
    queryset = ReorderingRule.objects.filter(active=True).select_related(
        "product__product_template", "location", "warehouse",
    )
    serializer_class = ReorderingRuleSerializer
    permission_classes = [IsAuthenticated, HasErpPermission]
    erp_resource = "inventory"
    filterset_fields = ["product", "warehouse"]

    @action(detail=False, methods=["post"], url_path="replenish")
    def replenish(self, request):
        """Create receipts for every rule whose forecast has fallen below its minimum."""
        try:
            created = StockService.run_replenishment()
        except ValueError as e:
            raise ValidationError(str(e))
        if created:
            NotificationService.create_notification(
                user=request.user,
                notification_type=NotificationType.REPLENISHMENT_CREATED,
                title="Replenishment receipts created",
                message=f"{len(created)} receipt(s) were created to restock low locations.",
                metadata={"picking_ids": [str(p.id) for p in created]},
            )
        return Response({"success": True, "created": len(created)})


class ScrapOrderViewSet(InventoryErrorMixin, mixins.ListModelMixin, mixins.CreateModelMixin,
                        mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Scrapped stock. Created as drafts; validate moves the stock to the scrap location."""
    queryset = ScrapOrder.objects.all().select_related(
        "product__product_template", "lot", "location", "scrap_location", "product__product_template__uom",
    )
    serializer_class = ScrapOrderSerializer
    permission_classes = [IsAuthenticated, HasErpPermission]
    erp_resource = "inventory"
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["name", "origin"]
    filterset_fields = ["state", "product"]

    @action(detail=True, methods=["post"])
    def validate(self, request, pk=None):
        scrap = self.get_object()
        try:
            StockService.validate_scrap(scrap)
        except ValueError as e:
            raise ValidationError(str(e))
        NotificationService.create_notification(
            user=request.user,
            notification_type=NotificationType.SCRAP_VALIDATED,
            title="Scrap order validated",
            message=f"Scrap order {scrap.name} moved {scrap.quantity} to the scrap location.",
            metadata={"scrap_id": str(scrap.id)},
        )
        return Response(ScrapOrderSerializer(scrap).data)


class ForecastViewSet(InventoryErrorMixin, viewsets.ViewSet):
    """Forecasted stock per product and location: on hand + incoming - outgoing."""
    permission_classes = [IsAuthenticated, HasErpPermission]
    erp_resource = "inventory"

    def list(self, request):
        warehouse = None
        warehouse_id = request.query_params.get("warehouse")
        if warehouse_id:
            warehouse = Warehouse.objects.filter(pk=warehouse_id).first()
        product = request.query_params.get("product") or None
        rows = StockService.get_forecast(warehouse=warehouse, product=product)
        return Response({"count": len(rows), "results": rows})


class StockLedgerViewSet(InventoryErrorMixin, viewsets.ReadOnlyModelViewSet):
    """Append-only history of stock changes, newest first."""
    queryset = StockLedgerEntry.objects.all().select_related("product__product_template", "location", "lot")
    serializer_class = StockLedgerEntrySerializer
    permission_classes = [IsAuthenticated, HasErpPermission]
    erp_resource = "inventory"
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["reference_name", "product__product_template__name"]
    filterset_fields = ["product", "location", "change_type", "reference_type", "reference_id"]

    def get_queryset(self):
        queryset = super().get_queryset()
        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")
        if date_from:
            queryset = queryset.filter(created_at__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(created_at__date__lte=date_to)
        return queryset


class ValuationViewSet(InventoryErrorMixin, viewsets.ViewSet):
    """Stock value per product and location, from the open FIFO cost layers."""
    permission_classes = [IsAuthenticated, HasErpPermission]
    erp_resource = "inventory"

    def list(self, request):
        warehouse = None
        warehouse_id = request.query_params.get("warehouse")
        if warehouse_id:
            warehouse = Warehouse.objects.filter(pk=warehouse_id).first()
        product = request.query_params.get("product") or None
        rows = valuation.get_valuation(warehouse=warehouse, product=product)
        total = sum((row["value"] for row in rows), Decimal("0"))
        return Response({"count": len(rows), "total_value": total, "results": rows})


class NrvViewSet(InventoryErrorMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """
    Net realisable value write-downs.
    GET lists recorded write-downs; POST runs the write-down for stock whose cost exceeds its sale price.
    """
    erp_action_map = {"create": "update"}
    queryset = InventoryNrvAdjustment.objects.all().select_related("product__product_template", "location")
    serializer_class = InventoryNrvAdjustmentSerializer
    permission_classes = [IsAuthenticated, HasErpPermission]
    erp_resource = "inventory"
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["product", "location"]

    def create(self, request):
        warehouse = None
        warehouse_id = request.data.get("warehouse")
        if warehouse_id:
            warehouse = Warehouse.objects.filter(pk=warehouse_id).first()
        adjustments = valuation.run_nrv(warehouse=warehouse, product=request.data.get("product") or None)
        if adjustments:
            NotificationService.create_notification(
                user=request.user,
                notification_type=NotificationType.GENERAL,
                title="NRV write-down posted",
                message=f"{len(adjustments)} product location(s) were written down to net realisable value.",
                metadata={"adjustment_ids": [str(a.id) for a in adjustments]},
            )
        return Response({"success": True, "created": len(adjustments)}, status=status.HTTP_201_CREATED)
