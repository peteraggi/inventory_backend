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

urlpatterns = router.urls
