from rest_framework.routers import DefaultRouter
from inventory_apps.erp_base.views import (
    CompanyViewSet, CurrencyViewSet, PartnerViewSet, PaymentTermViewSet,
    UomCategoryViewSet, UnitOfMeasureViewSet, ProductCategoryViewSet,
    TaxGroupViewSet, TaxViewSet, ProductTemplateViewSet, TenantModuleViewSet,
    ProductAttributeViewSet, ProductVariantViewSet,
)

router = DefaultRouter()
router.register("companies", CompanyViewSet, basename="company")
router.register("currencies", CurrencyViewSet, basename="currency")
router.register("partners", PartnerViewSet, basename="partner")
router.register("payment-terms", PaymentTermViewSet, basename="payment-term")
router.register("uom-categories", UomCategoryViewSet, basename="uom-category")
router.register("uom", UnitOfMeasureViewSet, basename="uom")
router.register("product-categories", ProductCategoryViewSet, basename="product-category")
router.register("tax-groups", TaxGroupViewSet, basename="tax-group")
router.register("taxes", TaxViewSet, basename="tax")
router.register("products", ProductTemplateViewSet, basename="product")
router.register("modules", TenantModuleViewSet, basename="tenant-module")
router.register("attributes", ProductAttributeViewSet, basename="product-attribute")
router.register("product-variants", ProductVariantViewSet, basename="product-variant")

urlpatterns = router.urls
