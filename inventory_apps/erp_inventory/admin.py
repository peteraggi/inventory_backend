from django.contrib import admin
from inventory_apps.erp_inventory.models import (
    Warehouse, StockLocation, StockPickingType, StockLot,
    StockPicking, StockMove, StockQuant,
    StockInventoryAdjustment, StockInventoryAdjustmentLine, ReorderingRule,
)

admin.site.register(Warehouse)
admin.site.register(StockLocation)
admin.site.register(StockPickingType)
admin.site.register(StockLot)
admin.site.register(StockPicking)
admin.site.register(StockMove)
admin.site.register(StockQuant)
admin.site.register(StockInventoryAdjustment)
admin.site.register(StockInventoryAdjustmentLine)
admin.site.register(ReorderingRule)
