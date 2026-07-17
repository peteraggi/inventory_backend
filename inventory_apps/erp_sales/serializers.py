from rest_framework import serializers
from inventory_apps.erp_sales.models import SaleOrder, SaleOrderLine


class SaleOrderLineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = SaleOrderLine
        fields = [
            "id", "product", "product_name", "description",
            "product_uom_qty", "qty_delivered", "qty_invoiced",
            "price_unit", "discount",
            "price_subtotal", "tax_amount", "price_total",
            "sequence",
        ]
        read_only_fields = ["price_subtotal", "tax_amount", "price_total", "qty_delivered", "qty_invoiced"]


class SaleOrderSerializer(serializers.ModelSerializer):
    lines = SaleOrderLineSerializer(many=True)
    partner_name = serializers.CharField(source="partner.name", read_only=True)
    state_display = serializers.CharField(source="get_state_display", read_only=True)
    invoice_status = serializers.CharField(read_only=True)
    payment_term_name = serializers.SerializerMethodField()

    class Meta:
        model = SaleOrder
        fields = [
            "id", "name", "partner", "partner_name",
            "state", "state_display",
            "date_order", "validity_date",
            "payment_term", "payment_term_name", "warehouse", "currency",
            "note", "client_order_ref",
            "amount_untaxed", "amount_tax", "amount_total",
            "delivery_count", "invoice_count",
            "invoice_status", "lines",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "name", "state", "amount_untaxed", "amount_tax", "amount_total",
            "delivery_count", "invoice_count",
        ]

    def get_payment_term_name(self, obj):
        return obj.payment_term.name if obj.payment_term_id else ""

    def create(self, validated_data):
        lines_data = validated_data.pop("lines", [])
        order = SaleOrder.objects.create(**validated_data)
        for line_data in lines_data:
            SaleOrderLine.objects.create(order=order, **line_data)
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
                SaleOrderLine.objects.create(order=instance, **line_data)
            instance.compute_totals()
        return instance


class SaleOrderListSerializer(serializers.ModelSerializer):
    partner_name = serializers.CharField(source="partner.name", read_only=True)
    state_display = serializers.CharField(source="get_state_display", read_only=True)

    class Meta:
        model = SaleOrder
        fields = [
            "id", "name", "partner_name", "state", "state_display",
            "date_order", "amount_total", "delivery_count", "invoice_count",
        ]
