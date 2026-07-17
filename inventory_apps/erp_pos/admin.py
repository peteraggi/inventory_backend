from django.contrib import admin
from inventory_apps.erp_pos.models import (
    POSConfig, POSPaymentMethod, POSSession, POSOrder, POSOrderLine, POSPayment,
)

admin.site.register(POSConfig)
admin.site.register(POSPaymentMethod)
admin.site.register(POSSession)
admin.site.register(POSPayment)


class POSOrderLineInline(admin.TabularInline):
    model = POSOrderLine
    extra = 0


@admin.register(POSOrder)
class POSOrderAdmin(admin.ModelAdmin):
    list_display = ["name", "session", "partner", "state", "date_order", "amount_total"]
    search_fields = ["name"]
    list_filter = ["state", "session"]
    inlines = [POSOrderLineInline]
