# inventory_apps/erp_inventory/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from inventory_apps.erp_inventory.views import (
    WarehouseViewSet, StockLocationViewSet, StockPickingTypeViewSet,
    StockLotViewSet, StockPickingViewSet, StockMoveViewSet,
    StockQuantViewSet, InventoryAdjustmentViewSet, ReorderingRuleViewSet,
    ScrapOrderViewSet, ForecastViewSet, StockLedgerViewSet, ValuationViewSet, NrvViewSet,
)

router = DefaultRouter()
router.register(r"warehouses", WarehouseViewSet, basename="warehouse")
router.register(r"locations", StockLocationViewSet, basename="location")
router.register(r"picking-types", StockPickingTypeViewSet, basename="picking-type")
# Same viewset, name used by the frontend's operation-type screens.
router.register(r"operation-types", StockPickingTypeViewSet, basename="operation-type")
router.register(r"lots", StockLotViewSet, basename="lot")
router.register(r"pickings", StockPickingViewSet, basename="picking")
router.register(r"moves", StockMoveViewSet, basename="move")
# Same viewset, name used by the frontend's move report.
router.register(r"move-lines", StockMoveViewSet, basename="move-line")
router.register(r"quants", StockQuantViewSet, basename="quant")
router.register(r"adjustments", InventoryAdjustmentViewSet, basename="adjustment")
router.register(r"reordering-rules", ReorderingRuleViewSet, basename="reordering-rule")
router.register(r"scrap", ScrapOrderViewSet, basename="scrap")
router.register(r"forecast", ForecastViewSet, basename="forecast")
router.register(r"ledger", StockLedgerViewSet, basename="ledger")
router.register(r"valuation", ValuationViewSet, basename="valuation")
router.register(r"nrv", NrvViewSet, basename="nrv")

app_name = "erp_inventory"

urlpatterns = [
    path("", include(router.urls)),
]

# Available endpoints (mounted under /erp/inventory/):
"""
Warehouses & locations:
GET/POST          /warehouses/                       - List / create warehouses
GET/PUT/PATCH/DEL /warehouses/{id}/                  - Warehouse detail
GET/POST          /locations/                        - List / create stock locations
GET/PUT/PATCH/DEL /locations/{id}/                   - Location detail

Operation types:
GET               /operation-types/                  - List operation types (alias: /picking-types/)
GET               /operation-types/{id}/             - Operation type detail

Transfers (pickings):
GET/POST          /pickings/                         - List / create transfers
GET/PUT/PATCH/DEL /pickings/{id}/                    - Transfer detail
POST              /pickings/{id}/confirm/            - Draft -> Waiting
POST              /pickings/{id}/validate/           - Apply moves to stock
POST              /pickings/{id}/cancel/             - Cancel transfer
POST              /pickings/{id}/return/             - Create a draft reverse transfer of a done transfer
GET               /pickings/?is_return=true          - Only return transfers

Stock moves:
GET               /moves/  and  /move-lines/         - Stock move lines (filter: date_from, date_to, state, product)
GET               /moves/{id}/                       - Move detail

Quants & counts:
GET               /quants/                           - On-hand stock per product/location/lot
GET               /quants/report/?warehouse=         - Aggregated stock report
POST              /quants/apply/                     - Physical count: {"quants": [{"quant_id", "inventory_quantity"}]}

Lots, adjustments, reordering:
GET/POST          /lots/                             - List / create lots & serial numbers
GET/POST          /adjustments/                      - List / create inventory adjustments
POST              /adjustments/{id}/validate/        - Post adjustment differences to stock
GET/POST          /reordering-rules/                 - List / create reordering rules
POST              /reordering-rules/replenish/       - Create receipts for rules below minimum

Scrap & forecast:
GET/POST          /scrap/                            - List / create scrap orders (drafts)
POST              /scrap/{id}/validate/              - Move scrapped stock to the scrap location
GET               /forecast/?warehouse=&product=     - On hand, incoming, outgoing and forecasted qty

Ledger, valuation and NRV:
GET               /ledger/?product=&location=&change_type=&date_from=&date_to=  - Stock change history
GET               /valuation/?warehouse=&product=    - Quantity and value per product and location (FIFO layers)
GET               /nrv/                              - Recorded net realisable value write-downs
POST              /nrv/                              - Run write-down: {"warehouse": "...", "product": "..."} (optional)

Errors: every failure returns {"success": false, "error": "<message>", "details": {...}|null}.
"""
