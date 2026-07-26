from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django.contrib.contenttypes.models import ContentType

from inventory_apps.erp_base.models import ActivityLog
from inventory_apps.erp_base.serializers import ActivityLogSerializer
from inventory_apps.erp_purchase.models import PurchaseOrder, PurchaseOrderLine
from inventory_apps.erp_purchase.serializers import (
    PurchaseOrderSerializer, PurchaseOrderListSerializer, PurchaseOrderLineSerializer,
)
from inventory_apps.erp_purchase.services import PurchaseService

# Fields tracked for chatter change-log entries on PurchaseOrder, mirroring
# Odoo's tracking=True field convention (see ProductTemplateViewSet).
PO_TRACKED_FIELDS = {
    "partner_ref": "Vendor Reference",
    "date_planned": "Order Deadline",
    "payment_term": "Payment Terms",
    "notes": "Terms and Conditions",
}


class PurchaseOrderViewSet(viewsets.ModelViewSet):
    queryset = PurchaseOrder.objects.all().select_related(
        "partner", "company", "currency", "payment_term"
    ).prefetch_related("lines__product", "lines__taxes")
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["name", "partner__name", "origin"]
    filterset_fields = ["state", "partner"]

    def get_serializer_class(self):
        if self.action == "list":
            return PurchaseOrderListSerializer
        return PurchaseOrderSerializer

    def _log(self, order, body, message_type="tracking"):
        ActivityLog.objects.create(
            content_type=ContentType.objects.get_for_model(PurchaseOrder),
            object_id=str(order.pk),
            user=self.request.user if self.request.user.is_authenticated else None,
            message_type=message_type,
            body=body,
        )

    def perform_create(self, serializer):
        order = serializer.save()
        self._log(order, "Quotation created", message_type="note")

    def _format_tracked_value(self, field, value):
        if field == "payment_term":
            if not value:
                return "—"
            return str(value)
        if value in (None, ""):
            return "—"
        return str(value)

    def perform_update(self, serializer):
        instance = serializer.instance
        before = {f: getattr(instance, f) for f in PO_TRACKED_FIELDS}
        order = serializer.save()
        for field, label in PO_TRACKED_FIELDS.items():
            after_value = getattr(order, field)
            if before[field] != after_value:
                self._log(
                    order,
                    f"{label}: {self._format_tracked_value(field, before[field])} "
                    f"→ {self._format_tracked_value(field, after_value)}",
                )

    @action(detail=True, methods=["get", "post"], url_path="activity")
    def activity(self, request, pk=None):
        order = self.get_object()
        content_type = ContentType.objects.get_for_model(PurchaseOrder)
        if request.method == "POST":
            body = (request.data.get("body") or "").strip()
            if not body:
                return Response({"error": "Note body is required"}, status=status.HTTP_400_BAD_REQUEST)
            entry = ActivityLog.objects.create(
                content_type=content_type,
                object_id=str(order.pk),
                user=request.user if request.user.is_authenticated else None,
                message_type="comment",
                body=body,
            )
            return Response(ActivityLogSerializer(entry).data, status=status.HTTP_201_CREATED)
        entries = ActivityLog.objects.filter(
            content_type=content_type, object_id=str(order.pk),
        ).select_related("user").order_by("-created_at")
        return Response(ActivityLogSerializer(entries, many=True).data)

    @action(detail=True, methods=["post"])
    def send(self, request, pk=None):
        order = self.get_object()
        try:
            order.action_send()
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        self._log(order, "Request for Quotation sent to vendor", message_type="note")
        return Response(PurchaseOrderSerializer(order).data)

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        order = self.get_object()
        try:
            PurchaseService.confirm_purchase_order(order)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        self._log(order, "Purchase order confirmed", message_type="note")
        return Response(PurchaseOrderSerializer(order).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        order = self.get_object()
        order.action_cancel()
        self._log(order, "Order cancelled", message_type="note")
        return Response(PurchaseOrderSerializer(order).data)

    @action(detail=True, methods=["post"], url_path="create-bill")
    def create_bill(self, request, pk=None):
        order = self.get_object()
        try:
            move = PurchaseService.create_bill_from_po(order)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        self._log(order, f"Bill {move.name} created", message_type="note")
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
