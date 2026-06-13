# pos_app/urls.py

from django.urls import path
from .views import (
    # Store & Role views
    StoreListView,
    StoreDetailView,
    RoleListView,
    # Product views
    ProductListCreateView,
    ProductDetailView,
    LowStockProductsView,
    CategoryListCreateView,
    CategoryDetailView,
    # Invoice views
    InvoiceListCreateView,
    InvoiceDetailView,
    BulkInvoiceSyncView,
    # Dashboard & Analytics
    DashboardStatsView,
    SalesReportView,
    ProductReportView,
    # Sync views
    SyncStatusView,
    SyncHistoryView,
    # Profile
    UserProfileView,
    # Utility
    health_check,
)

app_name = "pos_app"

urlpatterns = [
    # ============================================
    # UTILITY ENDPOINTS (Place first for priority)
    # ============================================
    path("health/", health_check, name="health-check"),
    # ============================================
    # STORE & ROLE ENDPOINTS
    # ============================================
    path("stores/", StoreListView.as_view(), name="store-list"),
    path("stores/me/", StoreDetailView.as_view(), name="store-detail"),
    path("roles/", RoleListView.as_view(), name="role-list"),
    # ============================================
    # CATEGORY ENDPOINTS
    # ============================================
    path("categories/", CategoryListCreateView.as_view(), name="category-list-create"),
    path("categories/<uuid:pk>/", CategoryDetailView.as_view(), name="category-detail"),
    # ============================================
    # PRODUCT ENDPOINTS
    # NOTE: Specific paths MUST come before generic UUID paths
    # ============================================
    path(
        "products/low-stock/", LowStockProductsView.as_view(), name="low-stock-products"
    ),
    path("products/", ProductListCreateView.as_view(), name="product-list-create"),
    path("products/<uuid:pk>/", ProductDetailView.as_view(), name="product-detail"),
    # ============================================
    # INVOICE ENDPOINTS
    # NOTE: Specific paths MUST come before generic UUID paths
    # ============================================
    path(
        "invoices/bulk-sync/", BulkInvoiceSyncView.as_view(), name="invoice-bulk-sync"
    ),
    path("invoices/", InvoiceListCreateView.as_view(), name="invoice-list-create"),
    path("invoices/<uuid:pk>/", InvoiceDetailView.as_view(), name="invoice-detail"),
    # ============================================
    # DASHBOARD & ANALYTICS ENDPOINTS
    # ============================================
    path("dashboard/stats/", DashboardStatsView.as_view(), name="dashboard-stats"),
    path("reports/sales/", SalesReportView.as_view(), name="sales-report"),
    path("reports/products/", ProductReportView.as_view(), name="product-report"),
    # ============================================
    # SYNC ENDPOINTS
    # ============================================
    path("sync/status/", SyncStatusView.as_view(), name="sync-status"),
    path("sync/history/", SyncHistoryView.as_view(), name="sync-history"),
    # ============================================
    # PROFILE ENDPOINTS
    # ============================================
    path("profile/", UserProfileView.as_view(), name="user-profile"),
]
