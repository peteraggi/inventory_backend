from rest_framework import serializers
from inventory_apps.erp_pos.models import (
    POSConfig, POSPaymentMethod, POSSession, POSOrder, POSOrderLine, POSPayment,
)


class POSPaymentMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = POSPaymentMethod
        fields = ["id", "name", "is_cash", "journal", "active"]


class POSConfigSerializer(serializers.ModelSerializer):
    payment_methods = POSPaymentMethodSerializer(many=True, read_only=True)
    payment_method_ids = serializers.PrimaryKeyRelatedField(
        source="payment_methods", many=True, write_only=True,
        queryset=POSPaymentMethod.objects.all(), required=False,
    )
    current_session_id = serializers.SerializerMethodField()

    class Meta:
        model = POSConfig
        fields = [
            "id", "name", "journal", "payment_methods", "payment_method_ids",
            "state", "warehouse", "receipt_header", "receipt_footer",
            "active", "current_session_id",
        ]

    def get_current_session_id(self, obj):
        session = obj.current_session
        return str(session.id) if session else None


class POSSessionSerializer(serializers.ModelSerializer):
    config_name = serializers.CharField(source="config.name", read_only=True)
    order_count = serializers.IntegerField(read_only=True)
    total_payments = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True)

    class Meta:
        model = POSSession
        fields = [
            "id", "name", "config", "config_name", "state",
            "opened_at", "closed_at", "opening_notes", "closing_notes",
            "cash_register_balance_start", "cash_register_balance_end",
            "cash_register_difference",
            "order_count", "total_payments",
            "created_at",
        ]
        read_only_fields = ["name", "cash_register_difference"]


class POSPaymentSerializer(serializers.ModelSerializer):
    payment_method_name = serializers.CharField(source="payment_method.name", read_only=True)

    class Meta:
        model = POSPayment
        fields = ["id", "payment_method", "payment_method_name", "amount", "payment_date"]


class POSOrderLineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = POSOrderLine
        fields = [
            "id", "product", "product_name",
            "qty", "price_unit", "discount", "tax_exempt",
            "price_subtotal", "price_tax", "price_subtotal_incl",
            "note",
        ]
        read_only_fields = ["price_subtotal", "price_tax", "price_subtotal_incl"]


class POSOrderSerializer(serializers.ModelSerializer):
    lines = POSOrderLineSerializer(many=True)
    payments = POSPaymentSerializer(many=True, required=False)
    partner_name = serializers.CharField(source="partner.name", read_only=True)
    state_display = serializers.CharField(source="get_state_display", read_only=True)

    class Meta:
        model = POSOrder
        fields = [
            "id", "name", "session", "partner", "partner_name",
            "state", "state_display",
            "date_order",
            "amount_tax", "amount_total", "amount_paid", "amount_return",
            "note", "invoice",
            "lines", "payments",
            "created_at",
        ]
        read_only_fields = [
            "name", "state",
            "amount_tax", "amount_total", "amount_paid", "amount_return",
        ]

    def create(self, validated_data):
        lines_data = validated_data.pop("lines", [])
        payments_data = validated_data.pop("payments", [])
        order = POSOrder.objects.create(**validated_data)
        for line_data in lines_data:
            POSOrderLine.objects.create(order=order, **line_data)
        for pay_data in payments_data:
            POSPayment.objects.create(pos_order=order, session=order.session, **pay_data)
        order.compute_totals()
        return order


class POSOrderListSerializer(serializers.ModelSerializer):
    partner_name = serializers.CharField(source="partner.name", read_only=True)

    class Meta:
        model = POSOrder
        fields = [
            "id", "name", "partner_name", "state",
            "date_order", "amount_total", "amount_paid",
        ]


class OfflineSyncSerializer(serializers.Serializer):
    orders = serializers.ListField(child=serializers.DictField())
