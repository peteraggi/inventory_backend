from rest_framework import serializers
from inventory_apps.erp_base.models import (
    Company, Currency, Partner, PaymentTerm, PaymentTermLine,
    UomCategory, UnitOfMeasure, ProductCategory, Tax, TaxGroup,
    ProductTemplate, SequenceCounter,
)


class CurrencySerializer(serializers.ModelSerializer):
    class Meta:
        model = Currency
        fields = ["id", "name", "code", "symbol", "rate", "active"]


class CompanySerializer(serializers.ModelSerializer):
    currency_code = serializers.CharField(source="currency.code", read_only=True)

    class Meta:
        model = Company
        fields = [
            "id", "name", "currency", "currency_code", "logo",
            "street", "street2", "city", "state", "zip_code", "country",
            "phone", "email", "website", "tax_id", "active",
            "created_at", "updated_at",
        ]


class PaymentTermLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentTermLine
        fields = ["id", "value", "value_amount", "days"]


class PaymentTermSerializer(serializers.ModelSerializer):
    lines = PaymentTermLineSerializer(many=True, required=False)

    class Meta:
        model = PaymentTerm
        fields = ["id", "name", "note", "active", "lines", "created_at"]

    def create(self, validated_data):
        lines_data = validated_data.pop("lines", [])
        pt = PaymentTerm.objects.create(**validated_data)
        for line_data in lines_data:
            PaymentTermLine.objects.create(payment_term=pt, **line_data)
        return pt


class UomCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = UomCategory
        fields = ["id", "name"]


class UnitOfMeasureSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)

    class Meta:
        model = UnitOfMeasure
        fields = ["id", "name", "category", "category_name", "uom_type", "factor", "rounding", "active"]


class TaxGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaxGroup
        fields = ["id", "name", "sequence"]


class TaxSerializer(serializers.ModelSerializer):
    tax_group_name = serializers.CharField(source="tax_group.name", read_only=True)

    class Meta:
        model = Tax
        fields = [
            "id", "name", "type_tax_use", "amount_type", "amount",
            "tax_group", "tax_group_name", "price_include", "active", "description",
        ]


class ProductCategorySerializer(serializers.ModelSerializer):
    parent_name = serializers.CharField(source="parent.complete_name", read_only=True)

    class Meta:
        model = ProductCategory
        fields = ["id", "name", "complete_name", "parent", "parent_name", "costing_method", "active"]


class PartnerSerializer(serializers.ModelSerializer):
    display_address = serializers.CharField(read_only=True)
    payment_term_name = serializers.CharField(source="payment_term.name", read_only=True)

    class Meta:
        model = Partner
        fields = [
            "id", "name", "partner_type", "image", "is_customer", "is_vendor",
            "email", "phone", "mobile",
            "street", "street2", "city", "state", "zip_code", "country",
            "tax_id", "website", "notes", "credit_limit",
            "payment_term", "payment_term_name",
            "display_address", "active",
            "created_at", "updated_at",
        ]


class ProductTemplateSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.complete_name", read_only=True)
    uom_name = serializers.CharField(source="uom.name", read_only=True)
    qty_on_hand = serializers.DecimalField(
        max_digits=18, decimal_places=4, read_only=True,
    )
    qty_available = serializers.DecimalField(
        max_digits=18, decimal_places=4, read_only=True,
    )
    tax_names = serializers.SerializerMethodField()

    class Meta:
        model = ProductTemplate
        fields = [
            "id", "name", "internal_reference", "barcode",
            "description", "description_sale", "description_purchase",
            "product_type", "category", "category_name",
            "uom", "uom_name", "purchase_uom",
            "sale_price", "standard_price",
            "taxes", "tax_names",
            "active", "can_be_sold", "can_be_purchased", "available_in_pos",
            "image", "notes",
            "qty_on_hand", "qty_available",
            "created_at", "updated_at",
        ]

    def get_tax_names(self, obj):
        return [t.name for t in obj.taxes.all()]


class ProductTemplateListSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.complete_name", read_only=True)
    uom_name = serializers.CharField(source="uom.name", read_only=True)
    qty_on_hand = serializers.DecimalField(max_digits=18, decimal_places=4, read_only=True)

    class Meta:
        model = ProductTemplate
        fields = [
            "id", "name", "internal_reference", "barcode",
            "product_type", "category_name", "uom_name", "image",
            "sale_price", "standard_price",
            "qty_on_hand", "active",
        ]
