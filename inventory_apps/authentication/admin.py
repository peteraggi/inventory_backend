# authentication/admin.py

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html
from django.db.models import Count
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """
    Enhanced admin interface for User model with safe display methods.
    """

    list_display = [
        'email', 'name', 'username', 'store_display',
        'role_display', 'is_verified', 'is_active', 'created_at'
    ]
    list_filter = ['role', 'store', 'is_verified', 'is_active', 'is_staff', 'auth_provider', 'created_at']
    search_fields = ['email', 'name', 'username', 'phone']
    ordering = ['-created_at']
    readonly_fields = ['id', 'username', 'created_at', 'updated_at', 'last_login']

    # Enable autocomplete for foreign keys
    autocomplete_fields = ['store', 'role']

    fieldsets = (
        ('Authentication', {
            'fields': ('id', 'email', 'password', 'username')
        }),
        ('Personal Information', {
            'fields': ('name', 'phone', 'bio')
        }),
        ('Store & Role Assignment', {
            'fields': ('store', 'role'),
            'description': 'Store and role are required for regular users.'
        }),
        ('Permissions & Status', {
            'fields': (
                'is_active', 'is_staff', 'is_superuser', 'is_verified',
                'groups', 'user_permissions'
            ),
        }),
        ('Important Dates', {
            'fields': ('last_login', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
        ('Authentication Provider', {
            'fields': ('auth_provider',),
            'classes': ('collapse',)
        }),
    )

    add_fieldsets = (
        ('Required Information', {
            'classes': ('wide',),
            'fields': ('email', 'name', 'password1', 'password2'),
        }),
        ('Store & Role Assignment', {
            'classes': ('wide',),
            'fields': ('store', 'role'),
            'description': 'Required for regular users. Leave empty for superusers.'
        }),
        ('Permissions', {
            'classes': ('wide',),
            'fields': ('is_active', 'is_staff', 'is_superuser', 'is_verified'),
        }),
    )

    def store_display(self, obj):
        """
        Safely display store name with status indicator.
        """
        try:
            if obj.store is None:
                if obj.is_superuser or obj.is_staff:
                    return format_html('<span style="color: gray;">N/A (Admin)</span>')
                return format_html('<span style="color: red;">⚠️ No Store</span>')

            store_name = getattr(obj.store, 'name', 'Unknown')
            is_active = getattr(obj.store, 'is_active', False)

            if is_active:
                return format_html(
                    '<span style="color: green;">✓ {}</span>',
                    store_name
                )
            else:
                return format_html(
                    '<span style="color: orange;">⚠️ {} (Inactive)</span>',
                    store_name
                )
        except Exception as e:
            return format_html('<span style="color: red;">Error</span>')

    store_display.short_description = 'Store'
    store_display.admin_order_field = 'store__name'

    def role_display(self, obj):
        """
        Safely display role with color coding.
        """
        try:
            if obj.role is None:
                if obj.is_superuser:
                    return format_html(
                        '<span style="color: purple; font-weight: bold;">🔑 Superuser</span>'
                    )
                if obj.is_staff:
                    return format_html(
                        '<span style="color: blue; font-weight: bold;">👤 Staff</span>'
                    )
                return format_html('<span style="color: red;">⚠️ No Role</span>')

            role_name = getattr(obj.role, 'display_name', None) or getattr(obj.role, 'name', 'Unknown')

            # Color code by role type
            color_map = {
                'owner': 'purple',
                'manager': 'blue',
                'salesperson': 'green'
            }

            role_key = getattr(obj.role, 'name', '').lower()
            color = color_map.get(role_key, 'gray')

            return format_html(
                '<span style="color: {}; font-weight: bold;">{}</span>',
                color,
                role_name
            )
        except Exception as e:
            return format_html('<span style="color: red;">Error</span>')

    role_display.short_description = 'Role'
    role_display.admin_order_field = 'role__name'

    def get_queryset(self, request):
        """
        Optimize queryset with select_related to avoid N+1 queries.
        """
        qs = super().get_queryset(request)
        return qs.select_related('store', 'role')

    def save_model(self, request, obj, form, change):
        """
        Override save to handle validation properly.
        """
        try:
            # For superusers, skip store/role validation
            if obj.is_superuser or obj.is_staff:
                super().save_model(request, obj, form, change)
            else:
                # Ensure store and role are set for regular users
                if not obj.store:
                    from django.contrib import messages
                    messages.error(request, 'Regular users must be assigned to a store.')
                    return

                if not obj.role:
                    from django.contrib import messages
                    messages.error(request, 'Regular users must have a role assigned.')
                    return

                super().save_model(request, obj, form, change)

        except Exception as e:
            from django.contrib import messages
            messages.error(request, f'Error saving user: {str(e)}')

    actions = ['verify_users', 'activate_users', 'deactivate_users']

    def verify_users(self, request, queryset):
        """Bulk action to verify users."""
        updated = queryset.update(is_verified=True)
        self.message_user(request, f'{updated} user(s) verified successfully.')

    verify_users.short_description = 'Verify selected users'

    def activate_users(self, request, queryset):
        """Bulk action to activate users."""
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} user(s) activated successfully.')

    activate_users.short_description = 'Activate selected users'

    def deactivate_users(self, request, queryset):
        """Bulk action to deactivate users."""
        updated = queryset.update(is_active=False)
        self.message_user(request, f'{updated} user(s) deactivated successfully.')

    deactivate_users.short_description = 'Deactivate selected users'