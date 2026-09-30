from django.contrib import admin
from inventory_apps.erp_purchase.models import PurchaseOrder, PurchaseOrderLine


class PurchaseOrderLineInline(admin.TabularInline):
    model = PurchaseOrderLine
    extra = 0


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ["name", "partner", "state", "date_order", "amount_total"]
    search_fields = ["name", "partner__name"]
    list_filter = ["state"]
    inlines = [PurchaseOrderLineInline]
