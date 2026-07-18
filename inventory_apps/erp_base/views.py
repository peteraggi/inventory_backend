from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend

from inventory_apps.erp_base.models import (
    Company, Currency, Partner, PaymentTerm,
    UomCategory, UnitOfMeasure, ProductCategory, Tax, TaxGroup, ProductTemplate,
)
from inventory_apps.erp_base.serializers import (
    CompanySerializer, CurrencySerializer, PartnerSerializer, PaymentTermSerializer,
    UomCategorySerializer, UnitOfMeasureSerializer, ProductCategorySerializer,
    TaxSerializer, TaxGroupSerializer,
    ProductTemplateSerializer, ProductTemplateListSerializer,
)
from inventory_apps.erp_base.services import SetupService


class CurrencyViewSet(viewsets.ModelViewSet):
    queryset = Currency.objects.filter(active=True)
    serializer_class = CurrencySerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ["name", "code"]


class CompanyViewSet(viewsets.ModelViewSet):
    queryset = Company.objects.filter(active=True)
    serializer_class = CompanySerializer
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["post"], url_path="setup")
    def setup(self, request):
        result = SetupService.seed_default_data()
        return Response({"message": "Default data seeded", **result})


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

    @action(detail=False, url_path="low-stock")
    def low_stock(self, request):
        from django.db.models import Sum, F, ExpressionWrapper, DecimalField
        from inventory_apps.erp_inventory.models import StockQuant
        from decimal import Decimal
        products = (
            self.get_queryset()
            .filter(product_type="storable")
            .prefetch_related("quants")
        )
        low = [p for p in products if p.qty_on_hand <= Decimal("5")]
        return Response(ProductTemplateListSerializer(low, many=True).data)
