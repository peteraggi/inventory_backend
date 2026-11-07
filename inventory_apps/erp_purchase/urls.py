# inventory_apps/erp_purchase/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from inventory_apps.erp_purchase.views import PurchaseOrderViewSet

router = DefaultRouter()
router.register(r"orders", PurchaseOrderViewSet, basename="purchase-order")

app_name = "erp_purchase"

urlpatterns = [
    path("", include(router.urls)),
]

# Available endpoints (mounted under /erp/purchase/):
"""
Orders:
GET/POST          /orders/                           - List / create RFQs and purchase orders
GET/PUT/PATCH/DEL /orders/{id}/                      - Order detail (lines are locked after confirmation)
GET               /orders/?archived=true             - Archived orders
POST              /orders/{id}/send/                 - Mark RFQ as sent to vendor
POST              /orders/{id}/confirm/              - Confirm and raise the receipt
POST              /orders/{id}/cancel/               - Cancel (refused after receipt or billing)
POST              /orders/{id}/create-bill/          - Bill the unbilled quantities (accounting create)
GET               /orders/{id}/receipts/             - Receipts raised for this order
GET               /orders/{id}/bills/                - Vendor bills for this order
GET               /orders/{id}/activity/             - Chatter log (POST to add a note)
POST              /orders/{id}/archive/              - Archive
POST              /orders/{id}/unarchive/            - Restore from archive
GET               /orders/{id}/pdf/                  - RFQ / purchase order PDF

Errors: every failure returns {"success": false, "error": "<message>", "details": {...}|null}.
"""
