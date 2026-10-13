from rest_framework import serializers
from inventory_apps.erp_sales.models import SaleOrder, SaleOrderLine


class SaleOrderLineSerializer(serializers.ModelSerializer):
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


QUOTATION_TERM_FIELDS = [
    "delivery_days", "delivery_words", "validity_days", "validity_words",
    "payment_grace_days", "payment_words", "initial_payment_percentage",
    "last_payment_percentage", "payment_method_words", "bank_details",
]


class SaleOrderSerializer(serializers.ModelSerializer):
    lines = SaleOrderLineSerializer(many=True)
    partner_name = serializers.CharField(source="partner.name", read_only=True)
    partner_address_lines = serializers.SerializerMethodField()
    state_display = serializers.CharField(source="get_state_display", read_only=True)
    invoice_status = serializers.CharField(read_only=True)
    payment_term_name = serializers.SerializerMethodField()
    salesperson_name = serializers.CharField(source="salesperson.name", read_only=True, default="")
    salesperson_email = serializers.CharField(source="salesperson.email", read_only=True, default="")
    salesperson_phone = serializers.CharField(source="salesperson.phone", read_only=True, default="")
    salesperson_signature = serializers.ImageField(source="salesperson.signature", read_only=True, default=None)
    partner_email = serializers.CharField(source="partner.email", read_only=True, default="")
    partner_phone = serializers.CharField(source="partner.phone", read_only=True, default="")
    currency_name = serializers.CharField(source="currency.name", read_only=True, default="")
    currency_code = serializers.CharField(source="currency.code", read_only=True, default="")
    currency_symbol = serializers.CharField(source="currency.symbol", read_only=True, default="")
    revision_of_name = serializers.CharField(source="revision_of.name", read_only=True, default="")
    revision_family = serializers.SerializerMethodField()

    class Meta:
        model = SaleOrder
        fields = [
            "id", "name", "partner", "partner_name", "partner_address_lines",
            "partner_email", "partner_phone",
            "state", "state_display",
            "date_order", "validity_date",
            "payment_term", "payment_term_name", "warehouse", "currency",
            "currency_name", "currency_code", "currency_symbol",
            "salesperson", "salesperson_name", "salesperson_email",
            "salesperson_phone", "salesperson_signature",
            "note", "client_order_ref",
            *QUOTATION_TERM_FIELDS,
            "revision_of", "revision_of_name", "revision", "revision_family",
            "amount_untaxed", "amount_tax", "amount_total",
            "delivery_count", "invoice_count", "active",
            "invoice_status", "lines",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "name", "state", "amount_untaxed", "amount_tax", "amount_total",
            "delivery_count", "invoice_count", "active",
            "revision_of", "revision",
        ]

    def get_revision_family(self, obj):
        """The original quotation plus all of its revisions, oldest first."""
        root = obj.revision_of or obj
        family = [root, *root.revisions.order_by("revision")]
        if len(family) == 1:
            return []
        return SaleOrderListSerializer(family, many=True).data

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
    revision_count = serializers.SerializerMethodField()
    state_display = serializers.CharField(source="get_state_display", read_only=True)
    salesperson_name = serializers.CharField(source="salesperson.name", read_only=True, default="")

    class Meta:
        model = SaleOrder
        fields = [
            "id", "name", "partner", "partner_name", "state", "state_display",
            "date_order", "validity_date", "client_order_ref",
            "amount_untaxed", "amount_tax", "amount_total",
            "delivery_count", "invoice_count",
            "salesperson_name", "revision_of", "revision", "revision_count",
        ]

    def get_revision_count(self, obj):
        # Annotated by SaleOrderViewSet's list queryset; fall back to a query
        # when serialized elsewhere (e.g. a quotation's revision family).
        annotated = getattr(obj, "revision_count_annotated", None)
        return annotated if annotated is not None else obj.revisions.count()
