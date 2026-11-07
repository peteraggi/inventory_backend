from decimal import Decimal

from rest_framework import serializers
from inventory_apps.erp_inventory.models import (
    Warehouse, StockLocation, StockPickingType, StockLot,
    StockPicking, StockMove, StockQuant,
    StockInventoryAdjustment, StockInventoryAdjustmentLine,
    ReorderingRule, ScrapOrder, StockLedgerEntry, InventoryNrvAdjustment,
)
from inventory_apps.erp_inventory.services import StockService


class StockLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockLocation
        fields = [
            "id", "name", "complete_name", "usage", "parent",
            "warehouse", "is_scrap", "active", "notes",
        ]


class StockLocationNestedSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockLocation
        fields = ["id", "name", "complete_name", "usage"]


class WarehouseSerializer(serializers.ModelSerializer):
    locations = StockLocationSerializer(many=True, read_only=True)

    class Meta:
        model = Warehouse
        fields = [
            "id", "name", "short_name", "company", "active",
            "lot_stock_location", "wh_input_location", "wh_output_location",
            "locations",
        ]


class StockPickingTypeSerializer(serializers.ModelSerializer):
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)

    class Meta:
        model = StockPickingType
        fields = [
            "id", "name", "code", "warehouse", "warehouse_name",
            "default_location_src", "default_location_dest",
            "sequence_prefix", "active",
        ]


class StockLotSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = StockLot
        fields = ["id", "name", "product", "product_name", "ref", "expiration_date", "use_date", "active"]


class StockMoveSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    lot_name = serializers.CharField(source="lot.name", read_only=True, default=None)
    picking_name = serializers.CharField(source="picking.name", read_only=True, default=None)
    location_src_name = serializers.CharField(source="location_src.complete_name", read_only=True)
    location_dest_name = serializers.CharField(source="location_dest.complete_name", read_only=True)
    date = serializers.SerializerMethodField()
    reference = serializers.CharField(source="origin", read_only=True)
    qty_done = serializers.DecimalField(source="quantity_done", max_digits=18, decimal_places=4, read_only=True)

    def get_date(self, obj):
        # When the move was validated; moves that never were fall back to their last update.
        return serializers.DateTimeField().to_representation(obj.date_done or obj.updated_at)

    class Meta:
        model = StockMove
        fields = [
            "id", "date", "picking", "picking_name", "reference", "product", "product_name",
            "lot", "lot_name", "description",
            "product_uom_qty", "quantity_done", "qty_done",
            "location_src", "location_src_name",
            "location_dest", "location_dest_name",
            "state", "origin", "price_unit",
        ]


class QuantCountLineSerializer(serializers.Serializer):
    quant_id = serializers.UUIDField()
    inventory_quantity = serializers.DecimalField(max_digits=18, decimal_places=4)


class QuantCountSerializer(serializers.Serializer):
    quants = QuantCountLineSerializer(many=True, allow_empty=False)


class StockPickingSerializer(serializers.ModelSerializer):
    move_lines = StockMoveSerializer(many=True, read_only=True)
    picking_type_name = serializers.CharField(source="picking_type.name", read_only=True)
    partner_name = serializers.CharField(source="partner.name", read_only=True)
    location_src_name = serializers.CharField(source="location_src.complete_name", read_only=True)
    location_dest_name = serializers.CharField(source="location_dest.complete_name", read_only=True)

    class Meta:
        model = StockPicking
        fields = [
            "id", "name", "picking_type", "picking_type_name",
            "partner", "partner_name",
            "state", "scheduled_date", "date_done", "origin", "note",
            "location_src", "location_src_name", "location_dest", "location_dest_name",
            "move_lines", "created_at",
        ]


class StockMoveCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockMove
        fields = ["product", "lot", "description", "product_uom_qty", "price_unit"]


class StockPickingCreateSerializer(serializers.ModelSerializer):
    move_lines = StockMoveCreateSerializer(many=True, required=False)

    class Meta:
        model = StockPicking
        fields = [
            "picking_type", "partner", "scheduled_date", "origin", "note",
            "location_src", "location_dest", "move_lines",
        ]

    def create(self, validated_data):
        lines_data = validated_data.pop("move_lines", [])
        picking = StockPicking.objects.create(**validated_data)
        for line_data in lines_data:
            StockMove.objects.create(
                picking=picking,
                location_src=picking.location_src,
                location_dest=picking.location_dest,
                origin=picking.origin,
                **line_data,
            )
        return picking

    def update(self, instance, validated_data):
        validated_data.pop("move_lines", None)
        return super().update(instance, validated_data)


class StockQuantSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    location_name = serializers.CharField(source="location.complete_name", read_only=True)
    lot_name = serializers.CharField(source="lot.name", read_only=True)
    available_quantity = serializers.DecimalField(max_digits=18, decimal_places=4, read_only=True)

    class Meta:
        model = StockQuant
        fields = [
            "id", "product", "product_name",
            "location", "location_name",
            "lot", "lot_name",
            "quantity", "reserved_quantity", "available_quantity",
        ]


class AdjustmentLineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = StockInventoryAdjustmentLine
        fields = [
            "id", "product", "product_name", "lot",
            "theoretical_qty", "inventory_qty", "difference_qty",
        ]


class InventoryAdjustmentSerializer(serializers.ModelSerializer):
    lines = AdjustmentLineSerializer(many=True)

    class Meta:
        model = StockInventoryAdjustment
        fields = ["id", "name", "location", "date", "state", "note", "lines"]

    def create(self, validated_data):
        lines_data = validated_data.pop("lines", [])
        adj = StockInventoryAdjustment.objects.create(**validated_data)
        for line_data in lines_data:
            StockInventoryAdjustmentLine.objects.create(adjustment=adj, **line_data)
        return adj


class ReorderingRuleSerializer(serializers.ModelSerializer):
    """Reordering rule. Field names follow the frontend (product_min_qty / product_max_qty)."""
    product_name = serializers.CharField(source="product.name", read_only=True)
    location_name = serializers.CharField(source="location.complete_name", read_only=True)
    product_min_qty = serializers.DecimalField(source="min_qty", max_digits=18, decimal_places=4)
    product_max_qty = serializers.DecimalField(source="max_qty", max_digits=18, decimal_places=4)
    warehouse = serializers.PrimaryKeyRelatedField(queryset=Warehouse.objects.all(), required=False)
    qty_on_hand = serializers.SerializerMethodField()
    # Replenishment creates receipts, i.e. the buy route.
    route_name = serializers.SerializerMethodField()

    class Meta:
        model = ReorderingRule
        fields = [
            "id", "product", "product_name", "location", "location_name", "warehouse",
            "product_min_qty", "product_max_qty", "qty_multiple", "qty_on_hand",
            "route_name", "active",
        ]

    def get_qty_on_hand(self, obj):
        return StockService.quantity_at(obj.product, obj.location)

    def get_route_name(self, obj):
        return "Buy"

    def validate(self, attrs):
        location = attrs.get("location") or (self.instance.location if self.instance else None)
        warehouse = attrs.get("warehouse") or (location.warehouse if location else None)
        if warehouse is None:
            raise serializers.ValidationError({"location": "Location must belong to a warehouse."})
        attrs["warehouse"] = warehouse
        return attrs


class ScrapOrderSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    lot_name = serializers.CharField(source="lot.name", read_only=True, default=None)
    scrap_qty = serializers.DecimalField(source="quantity", max_digits=18, decimal_places=4, read_only=True)
    product_uom_name = serializers.SerializerMethodField()
    date = serializers.DateTimeField(source="created_at", read_only=True)
    # Optional on input: they default to the first warehouse's stock and the shared scrap location.
    location = serializers.PrimaryKeyRelatedField(queryset=StockLocation.objects.all(), required=False)
    scrap_location = serializers.PrimaryKeyRelatedField(queryset=StockLocation.objects.all(), required=False)

    class Meta:
        model = ScrapOrder
        fields = [
            "id", "name", "product", "product_name", "lot", "lot_name",
            "quantity", "scrap_qty", "product_uom_name", "location", "scrap_location",
            "origin", "state", "date",
        ]
        read_only_fields = ["id", "name", "state", "date"]

    def get_product_uom_name(self, obj):
        uom = obj.product.product_template.uom
        return uom.name if uom else ""

    def validate(self, attrs):
        if attrs.get("location") is None:
            try:
                attrs["location"] = StockService.default_stock_location()
            except ValueError as e:
                raise serializers.ValidationError({"location": str(e)})
        if attrs.get("scrap_location") is None:
            attrs["scrap_location"] = StockService.scrap_location()
        if attrs.get("quantity", Decimal("1")) <= 0:
            raise serializers.ValidationError({"quantity": "Quantity must be greater than zero."})
        return attrs


class StockLedgerEntrySerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    location_name = serializers.CharField(source="location.complete_name", read_only=True)
    lot_name = serializers.CharField(source="lot.name", read_only=True, default=None)

    class Meta:
        model = StockLedgerEntry
        fields = [
            "id", "created_at", "product", "product_name", "location", "location_name",
            "lot", "lot_name", "change_type", "quantity_change", "resulting_quantity",
            "unit_cost", "reference_type", "reference_id", "reference_name",
        ]
        read_only_fields = fields


class InventoryNrvAdjustmentSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    location_name = serializers.CharField(source="location.complete_name", read_only=True)

    class Meta:
        model = InventoryNrvAdjustment
        fields = [
            "id", "created_at", "product", "product_name", "location", "location_name",
            "quantity_basis", "cost_per_unit", "nrv_per_unit", "per_unit_adjustment", "total_adjustment",
        ]
        read_only_fields = fields
