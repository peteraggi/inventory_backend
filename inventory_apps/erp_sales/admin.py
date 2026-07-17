from django.contrib import admin
from inventory_apps.erp_sales.models import SaleOrder, SaleOrderLine


class SaleOrderLineInline(admin.TabularInline):
    model = SaleOrderLine
    extra = 0


@admin.register(SaleOrder)
class SaleOrderAdmin(admin.ModelAdmin):
    list_display = ["name", "partner", "state", "date_order", "amount_total"]
    search_fields = ["name", "partner__name"]
    list_filter = ["state"]
    inlines = [SaleOrderLineInline]
