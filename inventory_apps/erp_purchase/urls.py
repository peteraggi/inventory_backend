from rest_framework.routers import DefaultRouter
from inventory_apps.erp_purchase.views import PurchaseOrderViewSet

router = DefaultRouter()
router.register("orders", PurchaseOrderViewSet, basename="purchase-order")

urlpatterns = router.urls
