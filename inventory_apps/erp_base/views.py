from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django.contrib.contenttypes.models import ContentType

from inventory_apps.erp_base.models import (
    Company, Currency, Partner, PaymentTerm,
    UomCategory, UnitOfMeasure, ProductCategory, Tax, TaxGroup, ProductTemplate,
    ActivityLog, TenantModule,
    ProductAttribute, ProductTemplateAttributeLine, ProductVariant,
)
from inventory_apps.erp_base.serializers import (
    CompanySerializer, CurrencySerializer, CurrencyRateSerializer, PartnerSerializer,
    PaymentTermSerializer,
    UomCategorySerializer, UnitOfMeasureSerializer, ProductCategorySerializer,
    TaxSerializer, TaxGroupSerializer,
    ProductTemplateSerializer, ProductTemplateListSerializer,
    ActivityLogSerializer, TenantModuleSerializer,
    ProductAttributeSerializer, ProductTemplateAttributeLineSerializer, ProductVariantSerializer,
)
from inventory_apps.erp_base.services import SetupService, ProductVariantService

# Fields tracked for chatter change-log entries on ProductTemplate, and their
# display labels — mirrors Odoo's tracking=True field convention.
PRODUCT_TRACKED_FIELDS = {
    "name": "Name",
    "sale_price": "Sales Price",
    "standard_price": "Cost",
    "product_type": "Product Type",
    "category_id": "Category",
    "active": "Active",
    "can_be_sold": "Can be Sold",
    "can_be_purchased": "Can be Purchased",
    "available_in_pos": "Available in POS",
    "invoice_policy": "Invoicing Policy",
}


class CurrencyViewSet(viewsets.ModelViewSet):
    queryset = Currency.objects.filter(active=True)
    serializer_class = CurrencySerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ["name", "code"]

    @action(detail=True, methods=["get", "post"], url_path="rates")
    def rates(self, request, pk=None):
        currency = self.get_object()
        if request.method == "POST":
            ser = CurrencyRateSerializer(data={**request.data, "currency": currency.id})
            ser.is_valid(raise_exception=True)
            ser.save()
            return Response(ser.data, status=status.HTTP_201_CREATED)
        rates = currency.rates.order_by("-rate_date")[:60]
        return Response(CurrencyRateSerializer(rates, many=True).data)


class CompanyViewSet(viewsets.ModelViewSet):
    queryset = Company.objects.filter(active=True)
    serializer_class = CompanySerializer
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["post"], url_path="setup")
    def setup(self, request):
        result = SetupService.seed_default_data()
        return Response({"message": "Default data seeded", **result})


class TenantModuleViewSet(viewsets.ModelViewSet):
    """Settings → Modules: turn whole app modules on/off for this tenant.
    Rows are seeded (see SetupService); only `enabled` is ever written."""
    queryset = TenantModule.objects.all()
    serializer_class = TenantModuleSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None
    http_method_names = ["get", "patch", "head", "options"]


class PartnerViewSet(viewsets.ModelViewSet):
    queryset = Partner.objects.filter(active=True).select_related("payment_term")
    serializer_class = PartnerSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["name", "email", "phone", "tax_id"]
    filterset_fields = ["is_customer", "is_vendor", "partner_type"]

    @action(detail=False, url_path="customers")
    def customers(self, request):
        qs = self.get_queryset().filter(is_customer=True)
        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)
        return Response(self.get_serializer(qs, many=True).data)

    @action(detail=False, url_path="vendors")
    def vendors(self, request):
        qs = self.get_queryset().filter(is_vendor=True)
        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)
        return Response(self.get_serializer(qs, many=True).data)


class PaymentTermViewSet(viewsets.ModelViewSet):
    queryset = PaymentTerm.objects.filter(active=True).prefetch_related("lines")
    serializer_class = PaymentTermSerializer
    permission_classes = [IsAuthenticated]


class UomCategoryViewSet(viewsets.ModelViewSet):
    queryset = UomCategory.objects.all()
    serializer_class = UomCategorySerializer
    permission_classes = [IsAuthenticated]


class UnitOfMeasureViewSet(viewsets.ModelViewSet):
    queryset = UnitOfMeasure.objects.filter(active=True).select_related("category")
    serializer_class = UnitOfMeasureSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["category"]


class ProductCategoryViewSet(viewsets.ModelViewSet):
    queryset = ProductCategory.objects.filter(active=True)
    serializer_class = ProductCategorySerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ["name", "complete_name"]


class TaxGroupViewSet(viewsets.ModelViewSet):
    queryset = TaxGroup.objects.all()
    serializer_class = TaxGroupSerializer
    permission_classes = [IsAuthenticated]


class TaxViewSet(viewsets.ModelViewSet):
    queryset = Tax.objects.filter(active=True)
    serializer_class = TaxSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["name"]
    filterset_fields = ["type_tax_use", "amount_type"]


class ProductTemplateViewSet(viewsets.ModelViewSet):
    queryset = ProductTemplate.objects.filter(active=True).select_related(
        "category", "uom", "purchase_uom"
    ).prefetch_related("taxes", "supplier_taxes")
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["name", "internal_reference", "barcode"]
    filterset_fields = ["product_type", "category", "can_be_sold", "can_be_purchased", "available_in_pos"]

    def get_serializer_class(self):
        if self.action == "list":
            return ProductTemplateListSerializer
        return ProductTemplateSerializer

    def _format_tracked_value(self, field, value):
        if field == "category_id":
            if not value:
                return "—"
            category = ProductCategory.objects.filter(pk=value).first()
            return category.name if category else "—"
        if isinstance(value, bool):
            return "Yes" if value else "No"
        if value in (None, ""):
            return "—"
        return str(value)

    def perform_update(self, serializer):
        instance = serializer.instance
        before = {f: getattr(instance, f) for f in PRODUCT_TRACKED_FIELDS}
        product = serializer.save()
        changes = []
        for field, label in PRODUCT_TRACKED_FIELDS.items():
            after_value = getattr(product, field)
            if before[field] != after_value:
                changes.append(
                    f"{label}: {self._format_tracked_value(field, before[field])} "
                    f"→ {self._format_tracked_value(field, after_value)}"
                )
        if changes:
            content_type = ContentType.objects.get_for_model(ProductTemplate)
            for change in changes:
                ActivityLog.objects.create(
                    content_type=content_type,
                    object_id=str(product.pk),
                    user=self.request.user if self.request.user.is_authenticated else None,
                    message_type="tracking",
                    body=change,
                )

    @action(detail=True, methods=["get", "post"], url_path="activity")
    def activity(self, request, pk=None):
        product = self.get_object()
        content_type = ContentType.objects.get_for_model(ProductTemplate)
        if request.method == "POST":
            body = (request.data.get("body") or "").strip()
            if not body:
                return Response({"error": "Note body is required"}, status=status.HTTP_400_BAD_REQUEST)
            entry = ActivityLog.objects.create(
                content_type=content_type,
                object_id=str(product.pk),
                user=request.user if request.user.is_authenticated else None,
                message_type="note",
                body=body,
            )
            return Response(ActivityLogSerializer(entry).data, status=status.HTTP_201_CREATED)
        entries = ActivityLog.objects.filter(
            content_type=content_type, object_id=str(product.pk),
        ).select_related("user").order_by("-created_at")
        return Response(ActivityLogSerializer(entries, many=True).data)

    @action(detail=False, url_path="low-stock")
    def low_stock(self, request):
        from django.db.models import Sum, F, ExpressionWrapper, DecimalField
        from inventory_apps.erp_inventory.models import StockQuant
        from decimal import Decimal
        products = (
            self.get_queryset()
            .filter(product_type="storable")
            .prefetch_related("variants__quants")
        )
        low = [p for p in products if p.qty_on_hand <= Decimal("5")]
        return Response(ProductTemplateListSerializer(low, many=True).data)

    @action(detail=True, methods=["get", "put"], url_path="attribute-lines")
    def attribute_lines(self, request, pk=None):
        """GET: this product's current attribute lines (which attributes +
        which of their values apply). PUT: replace the whole set in one go
        — expects [{attribute: <uuid>, value_ids: [<uuid>, ...]}, ...] — then
        regenerates variants from the new lines (see ProductVariantService)."""
        product = self.get_object()
        if request.method == "GET":
            lines = product.attribute_lines.prefetch_related("values", "attribute")
            return Response(ProductTemplateAttributeLineSerializer(lines, many=True).data)

        incoming = request.data if isinstance(request.data, list) else []
        seen_attribute_ids = set()
        for line_data in incoming:
            serializer = ProductTemplateAttributeLineSerializer(data=line_data)
            serializer.is_valid(raise_exception=True)
            attribute = serializer.validated_data["attribute"]
            values = serializer.validated_data["values"]
            seen_attribute_ids.add(str(attribute.id))
            line, _ = ProductTemplateAttributeLine.objects.update_or_create(
                product_template=product, attribute=attribute,
            )
            line.values.set(values)

        product.attribute_lines.exclude(attribute_id__in=seen_attribute_ids).delete()
        ProductVariantService.regenerate_variants(product)

        lines = product.attribute_lines.prefetch_related("values", "attribute")
        return Response(ProductTemplateAttributeLineSerializer(lines, many=True).data)

    @action(detail=True, url_path="variants")
    def variants(self, request, pk=None):
        product = self.get_object()
        variants = product.variants.filter(active=True).prefetch_related("attribute_values")
        return Response(ProductVariantSerializer(variants, many=True).data)


class ProductAttributeViewSet(viewsets.ModelViewSet):
    """Settings/Inventory → Configuration → Attributes: reusable variant
    dimensions (Color, Size, …) with their possible values."""
    queryset = ProductAttribute.objects.all().prefetch_related("values")
    serializer_class = ProductAttributeSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None


class ProductVariantViewSet(viewsets.ModelViewSet):
    """Read + light edit (barcode, reference, price extra, active) of one
    generated variant. Variants themselves are created/archived only via
    ProductTemplateViewSet.attribute_lines, never directly.

    Also doubles as the product picker for every order-line form (sales,
    purchase, POS, invoices, bills) — those pick a variant, never a template
    directly, matching Odoo. `search` matches the variant's own reference/
    barcode or its template's name/reference/barcode."""
    queryset = (
        ProductVariant.objects.all()
        .select_related("product_template", "product_template__uom", "product_template__category")
        .prefetch_related("attribute_values", "product_template__taxes")
    )
    serializer_class = ProductVariantSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["product_template", "active", "product_template__available_in_pos"]
    search_fields = [
        "product_template__name", "product_template__internal_reference", "product_template__barcode",
        "internal_reference", "barcode",
    ]
    pagination_class = None
    http_method_names = ["get", "patch", "head", "options"]
