# pos_app/admin.py

from django.contrib import admin
from django.utils.html import format_html
from django.db.models import Sum, Count
from django.urls import reverse
from django.utils.safestring import mark_safe
from .models import (
    Store,
    Role,
    Category,
    Product,
    Invoice,
    InvoiceItem,
    SyncLog,
    DailySales,
)
from django.urls import path


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    """Admin interface for Store model"""

    list_display = [
        "name",
        "code",
        "tax_rate",
        "currency",
        "user_count",
        "product_count",
        "is_active",
        "created_at",
    ]
    list_filter = ["is_active", "currency", "created_at"]
    search_fields = ["name", "code", "email", "phone"]
    readonly_fields = ["id", "created_at", "updated_at"]

    fieldsets = (
        ("Basic Information", {"fields": ("id", "name", "code", "is_active")}),
        ("Contact Information", {"fields": ("address", "phone", "email")}),
        ("Business Settings", {"fields": ("tax_rate", "currency")}),
        (
            "Timestamps",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )

    def user_count(self, obj):
        """Display count of active users in store"""
        count = obj.users.filter(is_active=True).count()
        return format_html(
            '<span style="color: {};">{}</span>',
            "green" if count > 0 else "gray",
            count,
        )

    user_count.short_description = "Active Users"

    def product_count(self, obj):
        """Display count of active products in store"""
        count = obj.products.filter(is_active=True).count()
        return format_html(
            '<span style="color: {};">{}</span>',
            "green" if count > 0 else "gray",
            count,
        )

    product_count.short_description = "Active Products"


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    """Admin interface for Role model"""

    list_display = ["display_name", "name", "user_count", "created_at"]
    search_fields = ["name", "display_name", "description"]
    readonly_fields = ["id", "created_at", "updated_at"]

    fieldsets = (
        ("Role Information", {"fields": ("id", "name", "display_name", "description")}),
        ("Permissions", {"fields": ("permissions",), "classes": ("wide",)}),
        (
            "Timestamps",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )

    def user_count(self, obj):
        """Display count of users with this role"""
        from inventory_apps.authentication.models import User

        count = User.objects.filter(role=obj, is_active=True).count()
        return format_html('<span style="font-weight: bold;">{}</span>', count)

    user_count.short_description = "Users"


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    """Admin interface for Category model"""

    list_display = [
        "name",
        "store",
        "parent",
        "product_count",
        "is_active",
        "created_at",
    ]
    list_filter = ["store", "is_active", "created_at", "parent"]
    search_fields = ["name", "description", "store__name"]
    readonly_fields = ["id", "created_at", "updated_at"]
    autocomplete_fields = ["store", "parent"]

    fieldsets = (
        (
            "Category Information",
            {"fields": ("id", "name", "description", "store", "parent", "is_active")},
        ),
        (
            "Timestamps",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )

    def product_count(self, obj):
        """Display count of active products in category"""
        count = obj.products.filter(is_active=True).count()
        if count == 0:
            return format_html('<span style="color: gray;">0</span>')
        return format_html(
            '<a href="{}?category__id__exact={}" style="color: #417690;">{}</a>',
            reverse("admin:pos_app_product_changelist"),
            obj.id,
            count,
        )

    product_count.short_description = "Products"


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    """Admin interface for Product model with bulk upload"""

    # IMPORTANT: Set custom template for product list
    change_list_template = "admin/pos_app/product/change_list.html"

    list_display = [
        "code",
        "name",
        "store",
        "category",
        "price",
        "cost",
        "stock",
        "stock_status",
        "is_active",
        "created_at",
    ]
    list_filter = ["store", "category", "is_active", "created_at"]
    search_fields = ["name", "code", "barcode", "description", "store__name"]
    readonly_fields = [
        "id",
        "is_low_stock",
        "profit_margin",
        "created_at",
        "updated_at",
        "created_by",
    ]
    autocomplete_fields = ["store", "category", "created_by"]

    fieldsets = (
        (
            "Product Information",
            {"fields": ("id", "name", "code", "barcode", "description", "is_active")},
        ),
        ("Classification", {"fields": ("store", "category")}),
        ("Pricing", {"fields": ("price", "cost", "profit_margin")}),
        ("Inventory", {"fields": ("stock", "low_stock_threshold", "is_low_stock")}),
        ("Media", {"fields": ("image_url",)}),
        (
            "Metadata",
            {
                "fields": ("created_by", "created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    actions = ["export_as_csv", "mark_as_active", "mark_as_inactive"]

    def get_urls(self):
        """Add custom URLs for bulk operations"""
        urls = super().get_urls()
        custom_urls = [
            path(
                "download-template/",
                self.admin_site.admin_view(self.download_template_view),
                name="pos_app_product_download_template",
            ),
            path(
                "bulk-upload/",
                self.admin_site.admin_view(self.bulk_upload_view),
                name="pos_app_product_bulk_upload",
            ),
            path(
                "export-excel/",
                self.admin_site.admin_view(self.export_excel_view),
                name="pos_app_product_export_excel",
            ),
        ]
        return custom_urls + urls

    def download_template_view(self, request):
        """Wrapper for download template view"""
        from .views import download_product_template

        return download_product_template(request)

    def bulk_upload_view(self, request):
        """Wrapper for bulk upload view"""
        from .views import bulk_upload_products

        return bulk_upload_products(request)

    def export_excel_view(self, request):
        """Wrapper for export excel view"""
        from .views import export_products_excel

        return export_products_excel(request)

    def stock_status(self, obj):
        """Display stock status with color coding"""
        if obj.stock == 0:
            return format_html(
                '<span style="color: red; font-weight: bold;">⚠️ OUT OF STOCK</span>'
            )
        elif obj.is_low_stock:
            return format_html(
                '<span style="color: orange; font-weight: bold;">⚠️ LOW STOCK ({}/{})</span>',
                obj.stock,
                obj.low_stock_threshold,
            )
        return format_html(
            '<span style="color: green;">✓ IN STOCK ({})</span>', obj.stock
        )

    stock_status.short_description = "Stock Status"

    def profit_margin(self, obj):
        """Calculate and display profit margin"""
        if obj.cost and obj.cost > 0:
            margin = ((obj.price - obj.cost) / obj.cost) * 100
            color = "green" if margin > 20 else "orange" if margin > 0 else "red"
            return format_html('<span style="color: {};">{:.2f}%</span>', color, margin)
        return format_html('<span style="color: gray;">N/A</span>')

    profit_margin.short_description = "Profit Margin"

    def export_as_csv(self, request, queryset):
        """Export selected products as CSV"""
        import csv
        from django.http import HttpResponse

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = "attachment; filename=products_export.csv"
        writer = csv.writer(response)

        # Write header
        writer.writerow(
            ["code", "name", "category", "price", "cost", "stock", "barcode"]
        )

        # Write data
        for obj in queryset:
            writer.writerow(
                [
                    obj.code,
                    obj.name,
                    obj.category.name if obj.category else "",
                    obj.price,
                    obj.cost or "",
                    obj.stock,
                    obj.barcode or "",
                ]
            )

        return response

    export_as_csv.short_description = "Export selected as CSV"

    def mark_as_active(self, request, queryset):
        """Bulk action to activate products"""
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} product(s) marked as active.")

    mark_as_active.short_description = "Mark selected products as active"

    def mark_as_inactive(self, request, queryset):
        """Bulk action to deactivate products"""
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} product(s) marked as inactive.")

    mark_as_inactive.short_description = "Mark selected products as inactive"


class InvoiceItemInline(admin.TabularInline):
    """Inline admin for invoice items"""

    model = InvoiceItem
    extra = 0
    readonly_fields = ["total", "created_at"]
    fields = ["product", "product_name", "product_code", "quantity", "price", "total"]
    autocomplete_fields = ["product"]

    def has_add_permission(self, request, obj=None):
        """Prevent adding items to synced invoices"""
        if obj and obj.sync_status == "SYNCED":
            return False
        return super().has_add_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        """Prevent deleting items from synced invoices"""
        if obj and obj.sync_status == "SYNCED":
            return False
        return super().has_delete_permission(request, obj)


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    """Admin interface for Invoice model"""

    list_display = [
        "invoice_number",
        "store",
        "salesperson_display",
        "item_count",
        "total",
        "sync_status_badge",
        "created_at",
    ]
    list_filter = ["store", "sync_status", "created_at", "salesperson"]
    search_fields = [
        "invoice_number",
        "customer_name",
        "customer_phone",
        "customer_email",
        "salesperson__name",
        "salesperson__email",
    ]
    readonly_fields = [
        "id",
        "subtotal",
        "tax",
        "total",
        "synced_at",
        "created_at",
        "updated_at",
        "item_summary",
        "sync_status_display",  # Add display method to readonly
    ]
    autocomplete_fields = ["store", "salesperson"]
    inlines = [InvoiceItemInline]
    date_hierarchy = "created_at"

    fieldsets = (
        (
            "Invoice Information",
            {"fields": ("id", "invoice_number", "store", "salesperson")},
        ),
        (
            "Customer Information",
            {
                "fields": ("customer_name", "customer_phone", "customer_email"),
                "classes": ("collapse",),
            },
        ),
        ("Financial Details", {"fields": ("subtotal", "tax", "discount", "total")}),
        ("Items", {"fields": ("item_summary",)}),
        ("Additional Information", {"fields": ("notes",), "classes": ("collapse",)}),
        (
            "Sync Information",
            {
                "fields": (
                    "sync_status",
                    "sync_status_display",
                    "synced_at",
                ),  # Use both field and display
                "classes": ("collapse",),
            },
        ),
        (
            "Timestamps",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )

    def salesperson_display(self, obj):
        """Safely display salesperson name"""
        if obj.salesperson:
            try:
                name = getattr(obj.salesperson, "name", None)
                if name:
                    return name
                return getattr(obj.salesperson, "email", None) or getattr(
                    obj.salesperson, "username", "Unknown"
                )
            except Exception:
                return "Unknown"
        return format_html('<span style="color: red;">No Salesperson</span>')

    salesperson_display.short_description = "Salesperson"
    salesperson_display.admin_order_field = "salesperson"

    def sync_status_badge(self, obj):
        """Display sync status with color coding (for list display)"""
        status_config = {
            "PENDING": ("orange", "⏳"),
            "SYNCED": ("green", "✓"),
            "FAILED": ("red", "✗"),
        }
        color, icon = status_config.get(obj.sync_status, ("gray", "?"))
        return format_html(
            '<span style="color: {}; font-weight: bold;">{} {}</span>',
            color,
            icon,
            obj.get_sync_status_display(),
        )

    sync_status_badge.short_description = "Sync Status"

    def sync_status_display(self, obj):
        """Display sync status for detail view (readonly field)"""
        status_config = {
            "PENDING": ("orange", "⏳", "Pending Sync"),
            "SYNCED": ("green", "✓", "Synced"),
            "FAILED": ("red", "✗", "Failed"),
        }
        color, icon, text = status_config.get(obj.sync_status, ("gray", "?", "Unknown"))
        return format_html(
            '<div style="padding: 10px; background: #f9fafb; border-left: 4px solid {}; border-radius: 4px;">'
            '<span style="color: {}; font-weight: bold; font-size: 16px;">{} {}</span>'
            "</div>",
            color,
            color,
            icon,
            text,
        )

    sync_status_display.short_description = "Current Sync Status"

    def item_count(self, obj):
        """Display count of items in invoice"""
        try:
            count = obj.items.count()
            return format_html(
                '<span style="font-weight: bold;">{} item(s)</span>', count
            )
        except Exception:
            return format_html('<span style="color: gray;">N/A</span>')

    item_count.short_description = "Items"

    def item_summary(self, obj):
        """Display detailed item summary"""
        try:
            items = obj.items.all()
            if not items:
                return format_html('<span style="color: gray;">No items</span>')

            currency = "UGX"
            if hasattr(obj, "store") and obj.store:
                currency = getattr(obj.store, "currency", "UGX")

            html = '<table style="width: 100%; border-collapse: collapse;">'
            html += '<tr style="background: #f8f8f8; font-weight: bold;">'
            html += '<th style="padding: 8px; text-align: left;">Product</th>'
            html += '<th style="padding: 8px; text-align: center;">Qty</th>'
            html += '<th style="padding: 8px; text-align: right;">Price</th>'
            html += '<th style="padding: 8px; text-align: right;">Total</th>'
            html += "</tr>"

            for item in items:
                html += '<tr style="border-bottom: 1px solid #ddd;">'
                product_name = getattr(item, "product_name", "Unknown")
                product_code = getattr(item, "product_code", "N/A")
                quantity = getattr(item, "quantity", 0)
                price = getattr(item, "price", 0)
                total = getattr(item, "total", 0)

                html += (
                    f'<td style="padding: 8px;">{product_name} ({product_code})</td>'
                )
                html += f'<td style="padding: 8px; text-align: center;">{quantity}</td>'
                html += f'<td style="padding: 8px; text-align: right;">{currency} {price:,.2f}</td>'
                html += f'<td style="padding: 8px; text-align: right;">{currency} {total:,.2f}</td>'
                html += "</tr>"

            html += "</table>"
            return mark_safe(html)
        except Exception as e:
            return format_html(
                '<span style="color: red;">Error loading items: {}</span>', str(e)
            )

    item_summary.short_description = "Item Details"

    def has_delete_permission(self, request, obj=None):
        """Prevent deletion of synced invoices"""
        if obj and obj.sync_status == "SYNCED":
            return False
        return super().has_delete_permission(request, obj)


@admin.register(InvoiceItem)
class InvoiceItemAdmin(admin.ModelAdmin):
    """Admin interface for InvoiceItem model"""

    list_display = [
        "invoice",
        "product_code",
        "product_name",
        "quantity",
        "price",
        "total",
        "created_at",
    ]
    list_filter = ["created_at", "invoice__store"]
    search_fields = [
        "product_name",
        "product_code",
        "invoice__invoice_number",
        "product__name",
    ]
    readonly_fields = ["id", "total", "created_at"]
    autocomplete_fields = ["invoice", "product"]
    date_hierarchy = "created_at"

    fieldsets = (
        ("Invoice Item Information", {"fields": ("id", "invoice", "product")}),
        (
            "Product Details",
            {"fields": ("product_name", "product_code", "quantity", "price", "total")},
        ),
        ("Timestamp", {"fields": ("created_at",), "classes": ("collapse",)}),
    )


@admin.register(SyncLog)
class SyncLogAdmin(admin.ModelAdmin):
    """Admin interface for SyncLog model"""

    list_display = [
        "sync_type",
        "user",
        "store",
        "status_badge",
        "items_synced",
        "items_failed",
        "duration",
        "started_at",
    ]
    list_filter = ["sync_type", "status", "store", "started_at"]
    search_fields = ["user__name", "user__email", "store__name", "error_message"]
    readonly_fields = [
        "id",
        "user",
        "store",
        "sync_type",
        "status",
        "items_synced",
        "items_failed",
        "error_message",
        "details",
        "started_at",
        "completed_at",
        "duration",
    ]
    date_hierarchy = "started_at"

    fieldsets = (
        (
            "Sync Information",
            {"fields": ("id", "sync_type", "status", "user", "store")},
        ),
        ("Results", {"fields": ("items_synced", "items_failed", "duration")}),
        (
            "Error Details",
            {"fields": ("error_message", "details"), "classes": ("collapse",)},
        ),
        (
            "Timestamps",
            {"fields": ("started_at", "completed_at"), "classes": ("collapse",)},
        ),
    )

    def status_badge(self, obj):
        """Display status with color coding"""
        status_config = {
            "pending": ("gray", "⏳"),
            "in_progress": ("blue", "▶"),
            "completed": ("green", "✓"),
            "failed": ("red", "✗"),
        }
        color, icon = status_config.get(obj.status, ("gray", "?"))
        return format_html(
            '<span style="color: {}; font-weight: bold;">{} {}</span>',
            color,
            icon,
            obj.get_status_display(),
        )

    status_badge.short_description = "Status"

    def duration(self, obj):
        """Calculate sync duration"""
        if obj.completed_at and obj.started_at:
            delta = obj.completed_at - obj.started_at
            seconds = delta.total_seconds()
            if seconds < 60:
                return f"{seconds:.1f}s"
            else:
                minutes = seconds / 60
                return f"{minutes:.1f}m"
        return format_html('<span style="color: gray;">N/A</span>')

    duration.short_description = "Duration"

    def has_add_permission(self, request):
        """Prevent manual creation of sync logs"""
        return False

    def has_delete_permission(self, request, obj=None):
        """Allow deletion only for failed logs"""
        if obj and obj.status == "failed":
            return True
        return False


@admin.register(DailySales)
class DailySalesAdmin(admin.ModelAdmin):
    """Admin interface for DailySales model"""

    list_display = [
        "date",
        "store",
        "total_sales",
        "invoice_count",
        "items_sold",
        "avg_sale",
    ]
    list_filter = ["store", "date"]
    search_fields = ["store__name"]
    readonly_fields = [
        "id",
        "store",
        "date",
        "total_sales",
        "invoice_count",
        "items_sold",
        "avg_sale",
        "created_at",
        "updated_at",
    ]
    date_hierarchy = "date"

    fieldsets = (
        ("Sales Information", {"fields": ("id", "store", "date")}),
        (
            "Metrics",
            {"fields": ("total_sales", "invoice_count", "items_sold", "avg_sale")},
        ),
        (
            "Timestamps",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )

    def avg_sale(self, obj):
        """Calculate average sale amount"""
        if obj.invoice_count > 0:
            avg = obj.total_sales / obj.invoice_count
            return format_html(
                '<span style="font-weight: bold;">{} {:.2f}</span>',
                obj.store.currency,
                avg,
            )
        return format_html('<span style="color: gray;">N/A</span>')

    avg_sale.short_description = "Avg Sale"

    def has_add_permission(self, request):
        """Prevent manual creation"""
        return False

    def has_delete_permission(self, request, obj=None):
        """Prevent deletion"""
        return False


# Enable autocomplete for Store model
Store.autocomplete_fields = []
Store.search_fields = ["name", "code"]
