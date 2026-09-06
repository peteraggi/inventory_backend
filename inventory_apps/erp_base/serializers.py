from rest_framework import serializers
from inventory_apps.erp_base.models import (
    Company, Currency, CurrencyRate, Partner, PaymentTerm, PaymentTermLine,
    UomCategory, UnitOfMeasure, ProductCategory, Tax, TaxGroup,
    ProductTemplate, SequenceCounter, ActivityLog, TenantModule,
    ProductAttribute, ProductAttributeValue, ProductTemplateAttributeLine, ProductVariant,
)


class TenantModuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = TenantModule
        fields = ["id", "key", "name", "description", "enabled"]
        read_only_fields = ["id", "key", "name", "description"]


class CurrencySerializer(serializers.ModelSerializer):
    class Meta:
        model = Currency
        fields = ["id", "name", "code", "symbol", "rate", "active"]


class CurrencyRateSerializer(serializers.ModelSerializer):
    class Meta:
        model = CurrencyRate
        fields = ["id", "currency", "rate", "rate_date", "created_at"]
        read_only_fields = ["id", "created_at"]

    def create(self, validated_data):
        rate_record = super().create(validated_data)
        currency = rate_record.currency
        latest = currency.rates.order_by("-rate_date").first()
        if latest and latest.pk == rate_record.pk:
            currency.rate = rate_record.rate
            currency.save(update_fields=["rate"])
        return rate_record


class CompanySerializer(serializers.ModelSerializer):
    currency_code = serializers.CharField(source="currency.code", read_only=True)
    currency_symbol = serializers.CharField(source="currency.symbol", read_only=True)

    class Meta:
        model = Company
        fields = [
            "id", "name", "currency", "currency_code", "currency_symbol", "logo",
            "street", "street2", "city", "state", "zip_code", "country",
            "phone", "email", "website", "tax_id", "active",
            "report_layout", "report_table_style", "report_font",
            "report_primary_color", "report_secondary_color", "report_tagline",
            "report_footer", "report_bank_account", "report_paper_format", "report_show_qr",
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


class ProductAttributeValueSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(required=False)

    class Meta:
        model = ProductAttributeValue
        fields = ["id", "name", "html_color", "sequence"]


class ProductAttributeSerializer(serializers.ModelSerializer):
    values = ProductAttributeValueSerializer(many=True, required=False)

    class Meta:
        model = ProductAttribute
        fields = ["id", "name", "display_type", "sequence", "values"]

    def create(self, validated_data):
        values_data = validated_data.pop("values", [])
        attribute = ProductAttribute.objects.create(**validated_data)
        for value_data in values_data:
            value_data.pop("id", None)
            ProductAttributeValue.objects.create(attribute=attribute, **value_data)
        return attribute

    def update(self, instance, validated_data):
        values_data = validated_data.pop("values", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()

        if values_data is not None:
            kept_ids = set()
            for value_data in values_data:
                value_id = value_data.pop("id", None)
                if value_id:
                    ProductAttributeValue.objects.filter(id=value_id, attribute=instance).update(**value_data)
                    kept_ids.add(str(value_id))
                else:
                    new_value = ProductAttributeValue.objects.create(attribute=instance, **value_data)
                    kept_ids.add(str(new_value.id))
            instance.values.exclude(id__in=kept_ids).delete()
        return instance


class ProductTemplateAttributeLineSerializer(serializers.ModelSerializer):
    attribute_name = serializers.CharField(source="attribute.name", read_only=True)
    values = ProductAttributeValueSerializer(many=True, read_only=True)
    value_ids = serializers.PrimaryKeyRelatedField(
        source="values", queryset=ProductAttributeValue.objects.all(), many=True, write_only=True,
    )

    class Meta:
        model = ProductTemplateAttributeLine
        fields = ["id", "attribute", "attribute_name", "values", "value_ids"]


class ProductVariantSerializer(serializers.ModelSerializer):
    """Doubles as the shape returned to any order-line product picker
    (sales/purchase/POS/invoice/bill) — those pick a *variant*, never a
    template directly, matching Odoo. Read-only fields beyond the variant's
    own are delegated straight from the template (see ProductVariant's
    Python properties in erp_base/models.py)."""
    display_name = serializers.CharField(read_only=True)
    sale_price = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)
    attribute_values = ProductAttributeValueSerializer(many=True, read_only=True)
    template_name = serializers.CharField(source="product_template.name", read_only=True)
    product_type = serializers.CharField(read_only=True)
    uom = serializers.UUIDField(source="product_template.uom_id", read_only=True)
    uom_name = serializers.CharField(source="product_template.uom.name", read_only=True, default="")
    category_name = serializers.CharField(source="product_template.category.complete_name", read_only=True, default="")
    standard_price = serializers.DecimalField(source="product_template.standard_price", max_digits=18, decimal_places=2, read_only=True)
    taxes = serializers.PrimaryKeyRelatedField(source="product_template.taxes", many=True, read_only=True)
    tax_names = serializers.SerializerMethodField()
    supplier_taxes = serializers.PrimaryKeyRelatedField(source="product_template.supplier_taxes", many=True, read_only=True)
    supplier_tax_names = serializers.SerializerMethodField()
    available_in_pos = serializers.BooleanField(source="product_template.available_in_pos", read_only=True)

    class Meta:
        model = ProductVariant
        fields = [
            "id", "product_template", "template_name", "display_name", "attribute_values",
            "internal_reference", "barcode", "price_extra", "sale_price", "standard_price",
            "product_type", "uom", "uom_name", "category_name", "taxes", "tax_names",
            "supplier_taxes", "supplier_tax_names", "available_in_pos", "image", "active",
        ]
        read_only_fields = ["id", "product_template", "attribute_values"]

    def get_tax_names(self, obj):
        return [t.name for t in obj.product_template.taxes.all()]

    def get_supplier_tax_names(self, obj):
        return [t.name for t in obj.product_template.supplier_taxes.all()]


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
    attribute_lines = ProductTemplateAttributeLineSerializer(many=True, read_only=True)
    variants = serializers.SerializerMethodField()
    variant_count = serializers.SerializerMethodField()

    class Meta:
        model = ProductTemplate
        fields = [
            "id", "name", "internal_reference", "barcode",
            "description", "description_sale", "description_purchase",
            "product_type", "category", "category_name",
            "uom", "uom_name", "purchase_uom",
            "sale_price", "standard_price", "invoice_policy",
            "taxes", "tax_names",
            "active", "can_be_sold", "can_be_purchased", "available_in_pos",
            "is_favorite", "image", "notes",
            "qty_on_hand", "qty_available",
            "attribute_lines", "variants", "variant_count",
            "created_at", "updated_at",
        ]

    def get_tax_names(self, obj):
        return [t.name for t in obj.taxes.all()]

    def get_variants(self, obj):
        return ProductVariantSerializer(obj.variants.filter(active=True), many=True).data

    def get_variant_count(self, obj):
        return obj.variants.filter(active=True).count()


class ProductTemplateListSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.complete_name", read_only=True)
    uom_name = serializers.CharField(source="uom.name", read_only=True)
    qty_on_hand = serializers.DecimalField(max_digits=18, decimal_places=4, read_only=True)
    variant_count = serializers.SerializerMethodField()

    class Meta:
        model = ProductTemplate
        fields = [
            "id", "name", "internal_reference", "barcode",
            "product_type", "category_name", "uom_name", "image",
            "sale_price", "standard_price", "taxes", "supplier_taxes",
            "qty_on_hand", "active", "is_favorite", "variant_count",
        ]

    def get_variant_count(self, obj):
        return obj.variants.filter(active=True).count()


class ActivityLogSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.name", read_only=True, default="")

    class Meta:
        model = ActivityLog
        fields = ["id", "user", "user_name", "message_type", "body", "created_at"]
        read_only_fields = ["id", "user", "user_name", "message_type", "created_at"]
