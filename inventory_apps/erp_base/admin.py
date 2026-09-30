from django.contrib import admin
from inventory_apps.erp_base.models import (
    Company, Currency, Partner, PaymentTerm, PaymentTermLine,
    UomCategory, UnitOfMeasure, ProductCategory, TaxGroup, Tax, ProductTemplate,
)

admin.site.register(Company)
admin.site.register(Currency)
admin.site.register(Partner)
admin.site.register(PaymentTerm)
admin.site.register(PaymentTermLine)
admin.site.register(UomCategory)
admin.site.register(UnitOfMeasure)
admin.site.register(ProductCategory)
admin.site.register(TaxGroup)
admin.site.register(Tax)


@admin.register(ProductTemplate)
class ProductTemplateAdmin(admin.ModelAdmin):
    list_display = ["name", "internal_reference", "product_type", "sale_price", "standard_price", "active"]
    search_fields = ["name", "internal_reference", "barcode"]
    list_filter = ["product_type", "category", "active"]
