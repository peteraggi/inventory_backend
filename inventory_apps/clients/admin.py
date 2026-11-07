from django.contrib import admin
from .models import Client, Domain, SubscriptionPlan, WaitlistSignup


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
    list_display = ['name', 'schema_name', 'contact_email', 'plan', 'approval_status', 'is_active', 'on_trial', 'trial_ends', 'created_at']
    list_filter = ['approval_status', 'is_active', 'on_trial', 'plan']
    search_fields = ['name', 'contact_email', 'schema_name']
    readonly_fields = ['schema_name', 'approved_at', 'approved_by', 'created_at', 'updated_at']
    inlines = [DomainInline]
    actions = ['approve_businesses', 'deactivate_businesses', 'reactivate_businesses']

    @admin.action(description='Approve selected businesses')
    def approve_businesses(self, request, queryset):
        from inventory_apps.clients import approval
        for client in queryset:
            approval.approve(client, by_email=request.user.email)
        self.message_user(request, f'{queryset.count()} business(es) approved.')

    @admin.action(description='Deactivate selected businesses')
    def deactivate_businesses(self, request, queryset):
        from inventory_apps.clients import approval
        for client in queryset:
            approval.set_active(client, False)
        self.message_user(request, f'{queryset.count()} business(es) deactivated.')

    @admin.action(description='Reactivate selected businesses')
    def reactivate_businesses(self, request, queryset):
        from inventory_apps.clients import approval
        for client in queryset:
            approval.set_active(client, True)
        self.message_user(request, f'{queryset.count()} business(es) reactivated.')


@admin.register(WaitlistSignup)
class WaitlistSignupAdmin(admin.ModelAdmin):
    list_display = ['email', 'name', 'business_name', 'whatsapp', 'reason', 'created_at']
    list_filter = ['reason']
    search_fields = ['email', 'name', 'business_name', 'whatsapp']
    readonly_fields = ['created_at']
