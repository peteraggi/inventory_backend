from django.contrib import admin
from inventory_apps.erp_accounting.models import (
    AccountAccount, AccountJournal, AccountMove, AccountMoveLine, AccountPayment, AccountGroup,
)

admin.site.register(AccountGroup)
admin.site.register(AccountAccount)
admin.site.register(AccountJournal)
admin.site.register(AccountPayment)


class AccountMoveLineInline(admin.TabularInline):
    model = AccountMoveLine
    extra = 0
    fields = ["account", "name", "debit", "credit", "partner"]


@admin.register(AccountMove)
class AccountMoveAdmin(admin.ModelAdmin):
    list_display = ["name", "move_type", "state", "partner", "date", "amount_total", "payment_state"]
    search_fields = ["name", "partner__name", "ref"]
    list_filter = ["move_type", "state", "payment_state"]
    inlines = [AccountMoveLineInline]
