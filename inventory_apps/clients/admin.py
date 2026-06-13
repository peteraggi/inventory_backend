from django.contrib import admin
from .models import Client, Domain, SubscriptionPlan


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ['display_name', 'name', 'price_monthly', 'max_stores', 'max_users', 'max_products', 'is_active']
    list_filter = ['is_active']
    search_fields = ['name', 'display_name']


class DomainInline(admin.TabularInline):
    model = Domain
    extra = 1


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ['name', 'schema_name', 'contact_email', 'plan', 'on_trial', 'trial_ends', 'is_active', 'created_at']
    list_filter = ['is_active', 'on_trial', 'plan']
    search_fields = ['name', 'contact_email', 'schema_name']
    readonly_fields = ['schema_name', 'created_at', 'updated_at']
    inlines = [DomainInline]
