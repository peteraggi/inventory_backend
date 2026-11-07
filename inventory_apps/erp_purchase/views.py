from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from inventory_apps.authentication.permissions import HasErpPermission
from django_filters.rest_framework import DjangoFilterBackend
from django.contrib.contenttypes.models import ContentType

from rest_framework.exceptions import PermissionDenied

from inventory_apps.erp_base.models import ActivityLog, Company
from inventory_core.exceptions import inventory_exception_handler
from inventory_apps.erp_base.serializers import ActivityLogSerializer
from inventory_apps.erp_purchase.models import PurchaseOrder
from inventory_apps.erp_purchase.serializers import (
    PurchaseOrderSerializer, PurchaseOrderListSerializer,
)
from inventory_apps.erp_purchase.services import PurchaseService
from inventory_core.pdf import render_pdf

# Fields tracked for chatter change-log entries on PurchaseOrder, mirroring
# Odoo's tracking=True field convention (see ProductTemplateViewSet).
PO_TRACKED_FIELDS = {
    "partner_ref": "Vendor Reference",
    "date_planned": "Order Deadline",
    "payment_term": "Payment Terms",
    "notes": "Terms and Conditions",
}


class PurchaseErrorMixin:
    """Every purchasing endpoint returns {"success": False, "error": "..."} on failure."""

    def get_exception_handler(self):
        return inventory_exception_handler


class PurchaseOrderViewSet(PurchaseErrorMixin, viewsets.ModelViewSet):
    """
    Requests for quotation and purchase orders.

    Workflow: send (RFQ sent) -> confirm (raises the receipt) -> create-bill.
    cancel is refused once goods have arrived or the order is billed.
    Lines are locked after confirmation.
    """
    queryset = PurchaseOrder.objects.all().select_related(
        "partner", "company", "currency", "payment_term"
    ).prefetch_related("lines__product", "lines__taxes")
    permission_classes = [IsAuthenticated, HasErpPermission]
    erp_resource = "purchases"
    # Confirming, cancelling and archiving change the order, so they need update, not create.
    erp_action_map = {
        "send": "update",
        "confirm": "update",
        "cancel": "update",
        "create_bill": "update",
        "archive": "update",
        "unarchive": "update",
    }
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["name", "partner__name", "origin"]
    filterset_fields = ["state", "partner"]

    def get_serializer_class(self):
        if self.action == "list":
            return PurchaseOrderListSerializer
        return PurchaseOrderSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        if self.action == "list":
            if self.request.query_params.get("archived") == "true":
                return qs.filter(active=False)
            return qs.filter(active=True)
        return qs

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
        """Mark an RFQ as sent to the vendor."""
        order = self.get_object()
        order.action_send()
        self._log(order, "Request for Quotation sent to vendor", message_type="note")
        return Response(PurchaseOrderSerializer(order).data)

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        """Confirm the RFQ into a purchase order and raise its receipt."""
        order = self.get_object()
        PurchaseService.confirm_purchase_order(order)
        self._log(order, "Purchase order confirmed", message_type="note")
        return Response(PurchaseOrderSerializer(order).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        order = self.get_object()
        PurchaseService.cancel_purchase_order(order)
        self._log(order, "Order cancelled", message_type="note")
        return Response(PurchaseOrderSerializer(order).data)

    @action(detail=True, methods=["post"], url_path="create-bill")
    def create_bill(self, request, pk=None):
        """Bill the quantities not yet billed. Needs accounting create access."""
        if not request.user.has_erp_permission("accounting", "create"):
            raise PermissionDenied("You need accounting access to create vendor bills.")
        order = self.get_object()
        move = PurchaseService.create_bill_from_po(order)
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

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        order = self.get_object()
        order.active = False
        order.save(update_fields=["active"])
        self._log(order, "Archived", message_type="note")
        return Response(PurchaseOrderSerializer(order).data)

    @action(detail=True, methods=["post"])
    def unarchive(self, request, pk=None):
        order = self.get_object()
        order.active = True
        order.save(update_fields=["active"])
        self._log(order, "Restored from archive", message_type="note")
        return Response(PurchaseOrderSerializer(order).data)

    @action(detail=True, url_path="pdf")
    def pdf(self, request, pk=None):
        order = self.get_object()
        company = order.company or Company.objects.filter(active=True).first()
        currency = order.currency
        symbol = currency.symbol if currency else "₦"

        doc_type_label = "Request for Quotation" if order.state in ("draft", "sent") else "Purchase Order"

        lines = [
            {
                "description": line.description or line.product.name,
                "qty": f"{line.product_qty:.2f}",
                "unit_price": f"{line.price_unit:,.2f}",
                "taxes": ", ".join(t.name for t in line.taxes.all()) or "—",
                "subtotal": f"{line.price_subtotal:,.2f}",
            }
            for line in order.lines.all()
        ]

        context = {
            "company": company,
            "doc_type_label": doc_type_label,
            "doc_number": order.name,
            "partner_label": "Vendor",
            "partner": order.partner,
            "order_date": order.date_order.strftime("%d %b %Y") if order.date_order else "",
            "other_date": order.date_planned.strftime("%d %b %Y") if order.date_planned else "",
            "other_date_label": "Order Deadline",
            "reference": order.partner_ref,
            "payment_term": order.payment_term.name if order.payment_term_id else "",
            "lines": lines,
            "currency_symbol": symbol,
            "amount_untaxed": f"{order.amount_untaxed:,.2f}",
            "amount_tax": f"{order.amount_tax:,.2f}",
            "amount_total": f"{order.amount_total:,.2f}",
            "notes": order.notes,
        }
        filename = f"{order.name.replace('/', '_')}.pdf"
        return render_pdf("erp_base/order_pdf.html", context, filename)
