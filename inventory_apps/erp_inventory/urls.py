from rest_framework.routers import DefaultRouter
from inventory_apps.erp_inventory.views import (
    WarehouseViewSet, StockLocationViewSet, StockPickingTypeViewSet,
    StockLotViewSet, StockPickingViewSet, StockMoveViewSet,
    StockQuantViewSet, InventoryAdjustmentViewSet, ReorderingRuleViewSet,
)

router = DefaultRouter()
router.register("warehouses", WarehouseViewSet, basename="warehouse")
router.register("locations", StockLocationViewSet, basename="location")
router.register("picking-types", StockPickingTypeViewSet, basename="picking-type")
router.register("lots", StockLotViewSet, basename="lot")
router.register("pickings", StockPickingViewSet, basename="picking")
router.register("moves", StockMoveViewSet, basename="move")
router.register("quants", StockQuantViewSet, basename="quant")
router.register("adjustments", InventoryAdjustmentViewSet, basename="adjustment")
router.register("reordering-rules", ReorderingRuleViewSet, basename="reordering-rule")

urlpatterns = router.urls
