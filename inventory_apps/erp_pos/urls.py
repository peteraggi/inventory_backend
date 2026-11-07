# inventory_apps/erp_pos/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from inventory_apps.erp_pos.views import (
    POSConfigViewSet, POSPaymentMethodViewSet,
    POSSessionViewSet, POSOrderViewSet,
)

router = DefaultRouter()
router.register("configs", POSConfigViewSet, basename="pos-config")
router.register("payment-methods", POSPaymentMethodViewSet, basename="pos-payment-method")
router.register("sessions", POSSessionViewSet, basename="pos-session")
router.register("orders", POSOrderViewSet, basename="pos-order")

app_name = "erp_pos"

urlpatterns = [
    path("", include(router.urls)),
]

# Available endpoints (mounted under /erp/pos/):
"""
Registers and payment methods:
GET/POST          /configs/                          - List / create registers
GET/PUT/PATCH/DEL /configs/{id}/                     - Register detail
POST              /configs/{id}/open-session/        - Open a session (one open session per register)
GET/POST          /payment-methods/                  - List / create payment methods

Sessions (read-only records):
GET               /sessions/                         - List sessions
GET               /sessions/{id}/                    - Session detail
POST              /sessions/{id}/close/              - Close (refused while orders are unpaid drafts)
GET               /sessions/{id}/summary/            - Sales and payments by method
POST              /sessions/{id}/sync-offline/       - Upload offline sales: {"orders": [...]}
                                                       returns created, skipped and failed

Sales:
GET/POST          /orders/                           - List / create draft sales (payments may be included)
GET/PUT/PATCH     /orders/{id}/                      - Draft detail (paid or cancelled orders are read-only)
DELETE            /orders/{id}/                      - Delete a draft
POST              /orders/{id}/pay/                  - Finalize: stock, ledger entry, paid state
POST              /orders/{id}/cancel/               - Cancel a draft
GET               /orders/{id}/payments/             - Payments on this sale

Errors: every failure returns {"success": false, "error": "<message>", "details": {...}|null}.
"""
