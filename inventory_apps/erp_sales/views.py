from django.db.models import Count, Q, Sum
from django.utils import timezone
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
    filterset_fields = ["state", "partner", "revision_of"]

    def get_serializer_class(self):
        if self.action == "list":
            return SaleOrderListSerializer
        return SaleOrderSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        if self.action in ("list", "summary"):
            params = self.request.query_params
            if self.action == "list":
                qs = qs.annotate(revision_count_annotated=Count("revisions"))
            # `state__in=draft,sent` lets the Quotations view list both
            # quotation states in one request.
            if params.get("state__in"):
                qs = qs.filter(state__in=params["state__in"].split(","))
            # `root_only=true` hides revisions so the list can nest them
            # under their original quotation.
            if params.get("root_only") == "true":
                qs = qs.filter(revision_of__isnull=True)
            # `expired=true` — quotations past their validity date.
            if params.get("expired") == "true":
                qs = qs.filter(state__in=("draft", "sent"), validity_date__lt=timezone.localdate())
            if params.get("archived") == "true":
                return qs.filter(active=False)
            return qs.filter(active=True)
        return qs

    @action(detail=False)
    def summary(self, request):
        """Count and total per quotation status, for the Quotations page
        analytics cards. Quotations past their validity date are counted
        as "expired" instead of created/sent."""
        qs = self.filter_queryset(self.get_queryset())
        today = timezone.localdate()
        expired = Q(state__in=("draft", "sent"), validity_date__lt=today)
        buckets = {
            "created": Q(state="draft") & ~expired,
            "sent": Q(state="sent") & ~expired,
            "accepted": Q(state__in=("sale", "done")),
            "cancelled": Q(state="cancel"),
            "expired": expired,
            "all": Q(),
        }
        data = {}
        for key, cond in buckets.items():
            agg = qs.filter(cond).aggregate(count=Count("id"), total=Sum("amount_total"))
            data[key] = {"count": agg["count"], "sum": agg["total"] or 0}
        return Response(data)

    def _detail(self, order):
        return SaleOrderSerializer(order, context=self.get_serializer_context()).data

    def perform_create(self, serializer):
        # The salesperson is whoever is creating the order — not something
        # the "New Quotation" form asks for, so default it here rather than
        # leaving it blank.
        serializer.save(salesperson=self.request.user)

    @action(detail=True, methods=["post"])
    def send(self, request, pk=None):
        order = self.get_object()
        try:
            order.action_send()
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self._detail(order))

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        order = self.get_object()
        try:
            SalesService.confirm_sale_order(order)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self._detail(order))

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        order = self.get_object()
        order.action_cancel()
        return Response(self._detail(order))

    @action(detail=True, methods=["post"])
    def revise(self, request, pk=None):
        order = self.get_object()
        try:
            revision = SalesService.create_revision(order, user=request.user)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self._detail(revision), status=status.HTTP_201_CREATED)

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
        return Response(self._detail(order))

    @action(detail=True, methods=["post"])
    def unarchive(self, request, pk=None):
        order = self.get_object()
        order.active = True
        order.save(update_fields=["active"])
        return Response(self._detail(order))

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
