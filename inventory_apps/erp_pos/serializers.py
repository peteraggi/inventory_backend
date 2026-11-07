# inventory_apps/erp_pos/serializers.py

from rest_framework import serializers

from inventory_apps.erp_pos.exceptions import OrderStateError
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

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Payment amount must be greater than zero.")
        return value


class POSOrderLineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    price_unit = serializers.DecimalField(max_digits=18, decimal_places=4, required=False)

    class Meta:
        model = POSOrderLine
        fields = [
            "id", "product", "product_name",
            "qty", "price_unit", "discount", "tax_exempt",
            "price_subtotal", "price_tax", "price_subtotal_incl",
            "note",
        ]
        read_only_fields = ["price_subtotal", "price_tax", "price_subtotal_incl"]

    def validate_qty(self, value):
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


def _line_with_price(line_data):
    """A line sold without an explicit price takes the product's sale price."""
    if line_data.get("price_unit") is None:
        line_data["price_unit"] = line_data["product"].product_template.sale_price
    return line_data


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
            "note", "invoice", "external_ref",
            "lines", "payments",
            "created_at",
        ]
        read_only_fields = [
            "name", "state",
            "amount_tax", "amount_total", "amount_paid", "amount_return",
            "external_ref",
        ]

    def validate(self, attrs):
        session = attrs.get("session") or getattr(self.instance, "session", None)
        if session is not None and session.state != "opened":
            raise serializers.ValidationError({"session": "Orders can only be taken on an open session."})

        payments = attrs.get("payments", [])
        if session is not None and payments:
            accepted = set(session.config.payment_methods.values_list("pk", flat=True))
            for payment in payments:
                method = payment["payment_method"]
                if accepted and method.pk not in accepted:
                    raise serializers.ValidationError(
                        {"payments": f"{method.name} is not accepted on this register."}
                    )
        return attrs

    def create(self, validated_data):
        lines_data = validated_data.pop("lines", [])
        payments_data = validated_data.pop("payments", [])
        order = POSOrder.objects.create(**validated_data)
        for line_data in lines_data:
            POSOrderLine.objects.create(order=order, **_line_with_price(line_data))
        for pay_data in payments_data:
            POSPayment.objects.create(pos_order=order, session=order.session, **pay_data)
        order.compute_totals()
        return order

    def update(self, instance, validated_data):
        lines_data = validated_data.pop("lines", None)
        validated_data.pop("payments", None)  # payments are taken by the pay action only
        if (lines_data is not None or validated_data) and instance.state != "draft":
            raise OrderStateError("Only a new order can be changed. This one has already been paid or cancelled.")
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if lines_data is not None:
            instance.lines.all().delete()
            for line_data in lines_data:
                POSOrderLine.objects.create(order=instance, **_line_with_price(line_data))
            instance.compute_totals()
        return instance


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
