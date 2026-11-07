# inventory_apps/erp_sales/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from inventory_apps.erp_sales.views import SaleOrderViewSet

router = DefaultRouter()
router.register(r"orders", SaleOrderViewSet, basename="sale-order")

app_name = "erp_sales"

urlpatterns = [
    path("", include(router.urls)),
]

# Available endpoints (mounted under /erp/sales/):
"""
Orders:
GET/POST          /orders/                           - List / create quotations and sales orders
GET/PUT/PATCH/DEL /orders/{id}/                      - Order detail (lines are locked after confirmation)
GET               /orders/?archived=true             - Archived orders
POST              /orders/{id}/send/                 - Mark quotation as sent
POST              /orders/{id}/confirm/              - Confirm and raise the delivery
POST              /orders/{id}/cancel/               - Cancel (refused after delivery or invoicing)
POST              /orders/{id}/create-invoice/       - Invoice the uninvoiced quantities (accounting create)
GET               /orders/{id}/deliveries/           - Deliveries raised for this order
GET               /orders/{id}/invoices/             - Invoices for this order
POST              /orders/{id}/archive/              - Archive
POST              /orders/{id}/unarchive/            - Restore from archive
GET               /orders/{id}/pdf/                  - Quotation / order PDF

Errors: every failure returns {"success": false, "error": "<message>", "details": {...}|null}.
"""
