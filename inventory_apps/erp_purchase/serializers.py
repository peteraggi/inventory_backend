from rest_framework import serializers
from inventory_apps.erp_base.models import Tax
from inventory_apps.erp_purchase.models import PurchaseOrder, PurchaseOrderLine


class PurchaseOrderLineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_uom_name = serializers.CharField(source="product_uom.name", read_only=True, default="")
    taxes = serializers.PrimaryKeyRelatedField(
        many=True, required=False, queryset=Tax.objects.filter(active=True),
    )
    tax_names = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrderLine
        fields = [
            "id", "product", "product_name", "product_uom", "product_uom_name", "description",
            "product_qty", "qty_received", "qty_billed",
            "price_unit", "taxes", "tax_names",
            "price_subtotal", "tax_amount", "price_total",
            "date_planned", "sequence",
        ]
        read_only_fields = ["price_subtotal", "tax_amount", "price_total", "qty_received", "qty_billed"]

    def get_tax_names(self, obj):
        return [t.name for t in obj.taxes.all()]


def _create_line(order, line_data):
    taxes = line_data.pop("taxes", [])
    line = PurchaseOrderLine.objects.create(order=order, **line_data)
    line.taxes.set(taxes)
    line.compute_amount()
    return line


class PurchaseOrderSerializer(serializers.ModelSerializer):
    lines = PurchaseOrderLineSerializer(many=True)
    partner_name = serializers.CharField(source="partner.name", read_only=True)
    partner_address_lines = serializers.SerializerMethodField()
    state_display = serializers.CharField(source="get_state_display", read_only=True)
    payment_term_name = serializers.SerializerMethodField()
    billing_status = serializers.ReadOnlyField()
    partner_email = serializers.CharField(source="partner.email", read_only=True, default="")
    partner_phone = serializers.CharField(source="partner.phone", read_only=True, default="")
    currency_name = serializers.CharField(source="currency.name", read_only=True, default="")
    currency_code = serializers.CharField(source="currency.code", read_only=True, default="")
    currency_symbol = serializers.CharField(source="currency.symbol", read_only=True, default="")
    buyer_name = serializers.CharField(source="buyer.name", read_only=True, default="")
    buyer_email = serializers.CharField(source="buyer.email", read_only=True, default="")
    buyer_signature = serializers.ImageField(source="buyer.signature", read_only=True, default=None)

    class Meta:
        model = PurchaseOrder
        fields = [
            "id", "name", "partner", "partner_name", "partner_address_lines", "partner_ref",
            "partner_email", "partner_phone",
            "state", "state_display",
            "date_order", "date_planned", "date_approve",
            "payment_term", "payment_term_name", "currency", "currency_name", "currency_code", "currency_symbol",
            "notes", "origin",
            "buyer", "buyer_name", "buyer_email", "buyer_signature",
            "contact_person", "validity_days", "delivery_terms", "payment_method_words", "delivery_address",
            "amount_untaxed", "amount_tax", "amount_total",
            "receipt_count", "invoice_count", "billing_status", "active",
            "lines", "created_at", "updated_at",
        ]
        read_only_fields = [
            "name", "state", "amount_untaxed", "amount_tax", "amount_total",
            "receipt_count", "invoice_count", "date_approve", "active", "buyer",
        ]

    def get_payment_term_name(self, obj):
        return obj.payment_term.name if obj.payment_term_id else ""

    def get_partner_address_lines(self, obj):
        return obj.partner.address_lines if obj.partner_id else []

    def create(self, validated_data):
        lines_data = validated_data.pop("lines", [])
        order = PurchaseOrder.objects.create(**validated_data)
        for line_data in lines_data:
            _create_line(order, line_data)
        order.compute_totals()
        return order

    def update(self, instance, validated_data):
        lines_data = validated_data.pop("lines", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if lines_data is not None:
            instance.lines.all().delete()
            for line_data in lines_data:
                _create_line(instance, line_data)
            instance.compute_totals()
        return instance


class PurchaseOrderListSerializer(serializers.ModelSerializer):
    partner_name = serializers.CharField(source="partner.name", read_only=True)
    state_display = serializers.CharField(source="get_state_display", read_only=True)
    billing_status = serializers.ReadOnlyField()
    buyer_name = serializers.CharField(source="buyer.name", read_only=True, default="")

    class Meta:
        model = PurchaseOrder
        fields = [
            "id", "name", "partner", "partner_name", "partner_ref", "state", "state_display",
            "date_order", "date_planned", "amount_untaxed", "amount_tax", "amount_total",
            "receipt_count", "invoice_count", "billing_status", "buyer_name",
        ]
