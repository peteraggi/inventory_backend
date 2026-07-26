from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend

from inventory_apps.erp_base.models import Company
from inventory_apps.erp_sales.models import SaleOrder, SaleOrderLine
from inventory_apps.erp_sales.serializers import (
    SaleOrderSerializer, SaleOrderListSerializer, SaleOrderLineSerializer,
)
from inventory_apps.erp_sales.services import SalesService
from inventory_core.pdf import render_pdf


class SaleOrderViewSet(viewsets.ModelViewSet):
    queryset = SaleOrder.objects.all().select_related(
        "partner", "company", "currency", "payment_term", "warehouse"
    ).prefetch_related("lines__product")
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["name", "partner__name", "client_order_ref"]
    filterset_fields = ["state", "partner"]

    def get_serializer_class(self):
        if self.action == "list":
            return SaleOrderListSerializer
        return SaleOrderSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        if self.action == "list":
            if self.request.query_params.get("archived") == "true":
                return qs.filter(active=False)
            return qs.filter(active=True)
        return qs

    @action(detail=True, methods=["post"])
    def send(self, request, pk=None):
        order = self.get_object()
        try:
            order.action_send()
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(SaleOrderSerializer(order).data)

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        order = self.get_object()
        try:
            SalesService.confirm_sale_order(order)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(SaleOrderSerializer(order).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        order = self.get_object()
        order.action_cancel()
        return Response(SaleOrderSerializer(order).data)

    @action(detail=True, methods=["post"], url_path="create-invoice")
    def create_invoice(self, request, pk=None):
        order = self.get_object()
        try:
            move = SalesService.create_invoice_from_so(order)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        from inventory_apps.erp_accounting.serializers import AccountMoveSerializer
        return Response(AccountMoveSerializer(move).data, status=status.HTTP_201_CREATED)

    @action(detail=True, url_path="deliveries")
    def deliveries(self, request, pk=None):
        order = self.get_object()
        from inventory_apps.erp_inventory.models import StockPicking
        from inventory_apps.erp_inventory.serializers import StockPickingSerializer
        pickings = StockPicking.objects.filter(origin=order.name)
        return Response(StockPickingSerializer(pickings, many=True).data)

    @action(detail=True, url_path="invoices")
    def invoices(self, request, pk=None):
        order = self.get_object()
        from inventory_apps.erp_accounting.serializers import AccountMoveListSerializer
        return Response(AccountMoveListSerializer(order.invoices.all(), many=True).data)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        order = self.get_object()
        order.active = False
        order.save(update_fields=["active"])
        return Response(SaleOrderSerializer(order).data)

    @action(detail=True, methods=["post"])
    def unarchive(self, request, pk=None):
        order = self.get_object()
        order.active = True
        order.save(update_fields=["active"])
        return Response(SaleOrderSerializer(order).data)

    @action(detail=True, url_path="pdf")
    def pdf(self, request, pk=None):
        order = self.get_object()
        company = order.company or Company.objects.filter(active=True).first()
        currency = order.currency
        symbol = currency.symbol if currency else "₦"

        doc_type_label = "Quotation" if order.state in ("draft", "sent") else "Sales Order"

        lines = [
            {
                "description": line.description or line.product.name,
                "qty": f"{line.product_uom_qty:.2f}",
                "unit_price": f"{line.price_unit:,.2f}",
                "taxes": ", ".join(t.name for t in line.product.taxes.filter(active=True)) or "—",
                "subtotal": f"{line.price_subtotal:,.2f}",
            }
            for line in order.lines.all()
        ]

        context = {
            "company": company,
            "doc_type_label": doc_type_label,
            "doc_number": order.name,
            "partner_label": "Customer",
            "partner": order.partner,
            "order_date": order.date_order.strftime("%d %b %Y") if order.date_order else "",
            "other_date": order.validity_date.strftime("%d %b %Y") if order.validity_date else "",
            "other_date_label": "Expiration Date",
            "reference": order.client_order_ref,
            "payment_term": order.payment_term.name if order.payment_term_id else "",
            "lines": lines,
            "currency_symbol": symbol,
            "amount_untaxed": f"{order.amount_untaxed:,.2f}",
            "amount_tax": f"{order.amount_tax:,.2f}",
            "amount_total": f"{order.amount_total:,.2f}",
            "notes": order.note,
        }
        filename = f"{order.name.replace('/', '_')}.pdf"
        return render_pdf("erp_base/order_pdf.html", context, filename)
