from rest_framework import serializers
from inventory_apps.erp_base.models import Tax
from inventory_apps.erp_purchase.models import PurchaseOrder, PurchaseOrderLine


class OrderLineValidationMixin:
    """Quantities must be positive, prices and discounts must be sensible."""

    def validate_product_uom_qty(self, value):
        if value <= 0:
            raise serializers.ValidationError("Quantity must be greater than zero.")
        return value

    def validate_product_qty(self, value):
        if value <= 0:
            raise serializers.ValidationError("Quantity must be greater than zero.")
        return value

    def validate_price_unit(self, value):
        if value < 0:
            raise serializers.ValidationError("Price cannot be negative.")
        return value

    def validate_discount(self, value):
        if value < 0 or value > 100:
            raise serializers.ValidationError("Discount must be between 0 and 100 percent.")
        return value


class PurchaseOrderLineSerializer(OrderLineValidationMixin, serializers.ModelSerializer):
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

    class Meta:
        model = PurchaseOrder
        fields = [
            "id", "name", "partner", "partner_name", "partner_address_lines", "partner_ref",
            "state", "state_display",
            "date_order", "date_planned", "date_approve",
            "payment_term", "payment_term_name", "currency", "notes", "origin",
            "amount_untaxed", "amount_tax", "amount_total",
            "receipt_count", "invoice_count", "billing_status", "active",
            "lines", "created_at", "updated_at",
        ]
        read_only_fields = [
            "name", "state", "amount_untaxed", "amount_tax", "amount_total",
            "receipt_count", "invoice_count", "date_approve", "active",
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
        if lines_data is not None and instance.state not in ("draft", "sent"):
            raise serializers.ValidationError(
                {"lines": "Lines can only be changed while the RFQ is not yet confirmed."}
            )
        if "notes" in validated_data and validated_data["notes"] != instance.notes and instance.state not in ("draft", "sent"):
            raise serializers.ValidationError(
                {"notes": "Terms can only be changed while the RFQ is not yet confirmed."}
            )
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

    class Meta:
        model = PurchaseOrder
        fields = [
            "id", "name", "partner_name", "state", "state_display",
            "date_order", "amount_total", "receipt_count", "invoice_count",
        ]
