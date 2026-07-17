from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend

from inventory_apps.erp_purchase.models import PurchaseOrder, PurchaseOrderLine
from inventory_apps.erp_purchase.serializers import (
    PurchaseOrderSerializer, PurchaseOrderListSerializer, PurchaseOrderLineSerializer,
)
from inventory_apps.erp_purchase.services import PurchaseService


class PurchaseOrderViewSet(viewsets.ModelViewSet):
    queryset = PurchaseOrder.objects.all().select_related(
        "partner", "company", "currency", "payment_term"
    ).prefetch_related("lines__product")
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["name", "partner__name", "origin"]
    filterset_fields = ["state", "partner"]

    def get_serializer_class(self):
        if self.action == "list":
            return PurchaseOrderListSerializer
        return PurchaseOrderSerializer

    @action(detail=True, methods=["post"])
    def send(self, request, pk=None):
        order = self.get_object()
        try:
            order.action_send()
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(PurchaseOrderSerializer(order).data)

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        order = self.get_object()
        try:
            PurchaseService.confirm_purchase_order(order)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(PurchaseOrderSerializer(order).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        order = self.get_object()
        order.action_cancel()
        return Response(PurchaseOrderSerializer(order).data)

    @action(detail=True, methods=["post"], url_path="create-bill")
    def create_bill(self, request, pk=None):
        order = self.get_object()
        try:
            move = PurchaseService.create_bill_from_po(order)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        from inventory_apps.erp_accounting.serializers import AccountMoveSerializer
        return Response(AccountMoveSerializer(move).data, status=status.HTTP_201_CREATED)

    @action(detail=True, url_path="receipts")
    def receipts(self, request, pk=None):
        order = self.get_object()
        from inventory_apps.erp_inventory.models import StockPicking
        from inventory_apps.erp_inventory.serializers import StockPickingSerializer
        pickings = StockPicking.objects.filter(origin=order.name)
        return Response(StockPickingSerializer(pickings, many=True).data)

    @action(detail=True, url_path="bills")
    def bills(self, request, pk=None):
        order = self.get_object()
        from inventory_apps.erp_accounting.serializers import AccountMoveListSerializer
        return Response(AccountMoveListSerializer(order.bills.all(), many=True).data)
