from rest_framework.routers import DefaultRouter
from django.urls import path
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

urlpatterns = router.urls
