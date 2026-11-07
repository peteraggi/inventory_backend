# inventory_apps/erp_accounting/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from inventory_apps.erp_accounting.views import (
    AccountAccountViewSet, AccountJournalViewSet,
    AccountMoveViewSet, AccountPaymentViewSet, ReportViewSet,
)

router = DefaultRouter()
router.register("accounts", AccountAccountViewSet, basename="account")
router.register("journals", AccountJournalViewSet, basename="journal")
router.register("moves", AccountMoveViewSet, basename="move")
router.register("payments", AccountPaymentViewSet, basename="payment")
router.register("reports", ReportViewSet, basename="report")

app_name = "erp_accounting"

urlpatterns = [
    path("", include(router.urls)),
]

# Available endpoints (mounted under /erp/accounting/):
"""
Chart of accounts and journals:
GET/POST          /accounts/                         - List / create accounts (search: code, name)
GET/PUT/PATCH/DEL /accounts/{id}/                    - Account detail
GET/POST          /journals/                         - List / create journals
GET/PUT/PATCH/DEL /journals/{id}/                    - Journal detail

Entries, invoices and bills:
GET/POST          /moves/                            - List / create (drafts only are editable)
GET/PUT/PATCH     /moves/{id}/                       - Detail; posted documents are read-only
DELETE            /moves/{id}/                       - Delete (drafts only)
POST              /moves/{id}/post/                  - Post to the ledger
POST              /moves/{id}/cancel/                - Cancel a draft
POST              /moves/{id}/recompute-journal-items/ - Rebuild generated lines of a posted invoice or bill
POST              /moves/{id}/register-payment/      - Pay: {"journal", "amount", "date", "memo"}

Payments:
GET/POST          /payments/                         - List / create payments
GET/PUT/PATCH/DEL /payments/{id}/                    - Detail; posted payments are read-only
POST              /payments/{id}/post/               - Post a draft payment

Reports:
GET               /reports/trial-balance/?date_from=&date_to=
GET               /reports/profit-and-loss/?date_from=&date_to=
GET               /reports/aged-receivable/
GET               /reports/aged-payable/
GET               /reports/dashboard-summary/

Errors: every failure returns {"success": false, "error": "<message>", "details": {...}|null}.
"""
