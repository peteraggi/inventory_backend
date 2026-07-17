from rest_framework import serializers
from inventory_apps.erp_purchase.models import PurchaseOrder, PurchaseOrderLine


class PurchaseOrderLineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = PurchaseOrderLine
        fields = [
            "id", "product", "product_name", "description",
            "product_qty", "qty_received", "qty_billed",
            "price_unit",
            "price_subtotal", "tax_amount", "price_total",
            "date_planned", "sequence",
        ]
        read_only_fields = ["price_subtotal", "tax_amount", "price_total", "qty_received", "qty_billed"]


class PurchaseOrderSerializer(serializers.ModelSerializer):
    lines = PurchaseOrderLineSerializer(many=True)
    partner_name = serializers.CharField(source="partner.name", read_only=True)
    state_display = serializers.CharField(source="get_state_display", read_only=True)

    class Meta:
        model = PurchaseOrder
        fields = [
            "id", "name", "partner", "partner_name",
            "state", "state_display",
            "date_order", "date_planned", "date_approve",
            "payment_term", "currency", "notes", "origin",
            "amount_untaxed", "amount_tax", "amount_total",
            "receipt_count", "invoice_count",
            "lines", "created_at", "updated_at",
        ]
        read_only_fields = [
            "name", "state", "amount_untaxed", "amount_tax", "amount_total",
            "receipt_count", "invoice_count", "date_approve",
        ]

    def create(self, validated_data):
        lines_data = validated_data.pop("lines", [])
        order = PurchaseOrder.objects.create(**validated_data)
        for line_data in lines_data:
            PurchaseOrderLine.objects.create(order=order, **line_data)
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
                PurchaseOrderLine.objects.create(order=instance, **line_data)
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
