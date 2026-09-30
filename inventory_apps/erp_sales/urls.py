from rest_framework.routers import DefaultRouter
from inventory_apps.erp_sales.views import SaleOrderViewSet

router = DefaultRouter()
router.register("orders", SaleOrderViewSet, basename="sale-order")

urlpatterns = router.urls
