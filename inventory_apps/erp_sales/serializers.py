from rest_framework import serializers
from inventory_apps.erp_sales.models import SaleOrder, SaleOrderLine


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


class SaleOrderLineSerializer(OrderLineValidationMixin, serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_uom_name = serializers.CharField(source="product_uom.name", read_only=True, default="")
    tax_names = serializers.SerializerMethodField()

    class Meta:
        model = SaleOrderLine
        fields = [
            "id", "product", "product_name", "product_uom", "product_uom_name", "description",
            "product_uom_qty", "qty_delivered", "qty_invoiced",
            "price_unit", "discount", "tax_names",
            "price_subtotal", "tax_amount", "price_total",
            "sequence",
        ]
        read_only_fields = ["price_subtotal", "tax_amount", "price_total", "qty_delivered", "qty_invoiced"]

    def get_tax_names(self, obj):
        if not obj.product_id:
            return []
        return [t.name for t in obj.product.taxes.filter(active=True)]


class SaleOrderSerializer(serializers.ModelSerializer):
    lines = SaleOrderLineSerializer(many=True)
    partner_name = serializers.CharField(source="partner.name", read_only=True)
    partner_address_lines = serializers.SerializerMethodField()
    state_display = serializers.CharField(source="get_state_display", read_only=True)
    invoice_status = serializers.CharField(read_only=True)
    payment_term_name = serializers.SerializerMethodField()
    salesperson_name = serializers.CharField(source="salesperson.name", read_only=True, default="")

    class Meta:
        model = SaleOrder
        fields = [
            "id", "name", "partner", "partner_name", "partner_address_lines",
            "state", "state_display",
            "date_order", "validity_date",
            "payment_term", "payment_term_name", "warehouse", "currency",
            "salesperson", "salesperson_name",
            "note", "client_order_ref",
            "amount_untaxed", "amount_tax", "amount_total",
            "delivery_count", "invoice_count", "active",
            "invoice_status", "lines",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "name", "state", "amount_untaxed", "amount_tax", "amount_total",
            "delivery_count", "invoice_count", "active",
        ]

    def get_payment_term_name(self, obj):
        return obj.payment_term.name if obj.payment_term_id else ""

    def get_partner_address_lines(self, obj):
        return obj.partner.address_lines if obj.partner_id else []

    def create(self, validated_data):
        lines_data = validated_data.pop("lines", [])
        order = SaleOrder.objects.create(**validated_data)
        for line_data in lines_data:
            SaleOrderLine.objects.create(order=order, **line_data)
        order.compute_totals()
        return order

    def update(self, instance, validated_data):
        lines_data = validated_data.pop("lines", None)
        if lines_data is not None and instance.state not in ("draft", "sent"):
            raise serializers.ValidationError(
                {"lines": "Lines can only be changed while the order is a quotation."}
            )
        if "note" in validated_data and validated_data["note"] != instance.note and instance.state not in ("draft", "sent"):
            raise serializers.ValidationError(
                {"note": "Terms can only be changed while the order is a quotation."}
            )
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if lines_data is not None:
            instance.lines.all().delete()
            for line_data in lines_data:
                SaleOrderLine.objects.create(order=instance, **line_data)
            instance.compute_totals()
        return instance


class SaleOrderListSerializer(serializers.ModelSerializer):
    partner_name = serializers.CharField(source="partner.name", read_only=True)
    state_display = serializers.CharField(source="get_state_display", read_only=True)
    salesperson_name = serializers.CharField(source="salesperson.name", read_only=True, default="")

    class Meta:
        model = SaleOrder
        fields = [
            "id", "name", "partner_name", "state", "state_display",
            "date_order", "amount_total", "delivery_count", "invoice_count",
            "salesperson_name",
        ]
