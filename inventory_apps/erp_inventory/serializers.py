from rest_framework import serializers
from inventory_apps.erp_inventory.models import (
    Warehouse, StockLocation, StockPickingType, StockLot,
    StockPicking, StockMove, StockQuant,
    StockInventoryAdjustment, StockInventoryAdjustmentLine,
    ReorderingRule,
)


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
    location_src_name = serializers.CharField(source="location_src.complete_name", read_only=True)
    location_dest_name = serializers.CharField(source="location_dest.complete_name", read_only=True)

    class Meta:
        model = StockMove
        fields = [
            "id", "picking", "product", "product_name",
            "lot", "description",
            "product_uom_qty", "quantity_done",
            "location_src", "location_src_name",
            "location_dest", "location_dest_name",
            "state", "origin", "price_unit",
        ]


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
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = ReorderingRule
        fields = [
            "id", "product", "product_name", "location", "warehouse",
            "min_qty", "max_qty", "qty_multiple", "active",
        ]
