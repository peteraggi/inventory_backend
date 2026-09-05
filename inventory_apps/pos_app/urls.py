# pos_app/urls.py

from django.urls import path
from .views import (
    # Store & Roles
    StoreListView,
    StoreDetailView,
    RoleListView,
    RoleDetailView,
    # Categories & Products
    CategoryListCreateView,
    CategoryDetailView,
    LowStockProductsView,
    ProductListCreateView,
    ProductDetailView,
    # POS Invoices
    BulkInvoiceSyncView,
    InvoiceListCreateView,
    InvoiceDetailView,
    # Dashboard & Reports
    DashboardStatsView,
    SalesReportView,
    ProductReportView,
    # Sync
    SyncStatusView,
    SyncHistoryView,
    # Profile & Utility
    UserProfileView,
    health_check,
    # Contacts
    ContactListCreateView,
    ContactDetailView,
    # Accounts & Journals
    AccountListCreateView,
    AccountDetailView,
    JournalListView,
    JournalEntryListView,
    JournalEntryDetailView,
    # Purchase
    PurchaseOrderListCreateView,
    PurchaseOrderDetailView,
    ConfirmPurchaseOrderView,
    GoodsReceiptListCreateView,
    GoodsReceiptDetailView,
    ValidateGoodsReceiptView,
    VendorBillListCreateView,
    VendorBillDetailView,
    ConfirmVendorBillView,
    # Sales
    SalesOrderListCreateView,
    SalesOrderDetailView,
    ConfirmSalesOrderView,
    DeliveryNoteListCreateView,
    DeliveryNoteDetailView,
    ValidateDeliveryNoteView,
    SalesInvoiceListCreateView,
    SalesInvoiceDetailView,
    PostSalesInvoiceView,
    # Payments & Reporting
    PaymentListCreateView,
    PaymentDetailView,
    ConfirmPaymentView,
    StockMoveListView,
    TrialBalanceView,
)

app_name = "pos_app"

urlpatterns = [
    # ── Utility ──────────────────────────────────────────────────────────────
    path("health/", health_check, name="health-check"),
    # ── Store & Roles ─────────────────────────────────────────────────────────
    path("stores/", StoreListView.as_view(), name="store-list"),
    path("stores/me/", StoreDetailView.as_view(), name="store-detail"),
    path("roles/", RoleListView.as_view(), name="role-list"),
    path("roles/<uuid:pk>/", RoleDetailView.as_view(), name="role-detail"),
    # ── Categories ────────────────────────────────────────────────────────────
    path("categories/", CategoryListCreateView.as_view(), name="category-list-create"),
    path("categories/<uuid:pk>/", CategoryDetailView.as_view(), name="category-detail"),
    # ── Products ──────────────────────────────────────────────────────────────
    path(
        "products/low-stock/", LowStockProductsView.as_view(), name="low-stock-products"
    ),
    path("products/", ProductListCreateView.as_view(), name="product-list-create"),
    path("products/<uuid:pk>/", ProductDetailView.as_view(), name="product-detail"),
    # ── POS Invoices ──────────────────────────────────────────────────────────
    path(
        "invoices/bulk-sync/", BulkInvoiceSyncView.as_view(), name="invoice-bulk-sync"
    ),
    path("invoices/", InvoiceListCreateView.as_view(), name="invoice-list-create"),
    path("invoices/<uuid:pk>/", InvoiceDetailView.as_view(), name="invoice-detail"),
    # ── Dashboard & Analytics ─────────────────────────────────────────────────
    path("dashboard/stats/", DashboardStatsView.as_view(), name="dashboard-stats"),
    path("reports/sales/", SalesReportView.as_view(), name="sales-report"),
    path("reports/products/", ProductReportView.as_view(), name="product-report"),
    path("reports/trial-balance/", TrialBalanceView.as_view(), name="trial-balance"),
    # ── Sync ──────────────────────────────────────────────────────────────────
    path("sync/status/", SyncStatusView.as_view(), name="sync-status"),
    path("sync/history/", SyncHistoryView.as_view(), name="sync-history"),
    # ── Profile ───────────────────────────────────────────────────────────────
    path("profile/", UserProfileView.as_view(), name="user-profile"),
    # ── Contacts ──────────────────────────────────────────────────────────────
    path("contacts/", ContactListCreateView.as_view(), name="contact-list-create"),
    path("contacts/<uuid:pk>/", ContactDetailView.as_view(), name="contact-detail"),
    # ── Chart of Accounts ─────────────────────────────────────────────────────
    path("accounts/", AccountListCreateView.as_view(), name="account-list-create"),
    path("accounts/<uuid:pk>/", AccountDetailView.as_view(), name="account-detail"),
    # ── Journals & Entries ────────────────────────────────────────────────────
    path("journals/", JournalListView.as_view(), name="journal-list"),
    path("journal-entries/", JournalEntryListView.as_view(), name="journal-entry-list"),
    path(
        "journal-entries/<uuid:pk>/",
        JournalEntryDetailView.as_view(),
        name="journal-entry-detail",
    ),
    # ── Purchase Orders ───────────────────────────────────────────────────────
    path(
        "purchase-orders/", PurchaseOrderListCreateView.as_view(), name="po-list-create"
    ),
    path(
        "purchase-orders/<uuid:pk>/",
        PurchaseOrderDetailView.as_view(),
        name="po-detail",
    ),
    path(
        "purchase-orders/<uuid:pk>/confirm/",
        ConfirmPurchaseOrderView.as_view(),
        name="po-confirm",
    ),
    # ── Goods Receipts ────────────────────────────────────────────────────────
    path(
        "goods-receipts/", GoodsReceiptListCreateView.as_view(), name="gr-list-create"
    ),
    path(
        "goods-receipts/<uuid:pk>/", GoodsReceiptDetailView.as_view(), name="gr-detail"
    ),
    path(
        "goods-receipts/<uuid:pk>/validate/",
        ValidateGoodsReceiptView.as_view(),
        name="gr-validate",
    ),
    # ── Vendor Bills ──────────────────────────────────────────────────────────
    path("vendor-bills/", VendorBillListCreateView.as_view(), name="vb-list-create"),
    path("vendor-bills/<uuid:pk>/", VendorBillDetailView.as_view(), name="vb-detail"),
    path(
        "vendor-bills/<uuid:pk>/confirm/",
        ConfirmVendorBillView.as_view(),
        name="vb-confirm",
    ),
    # ── Sales Orders ──────────────────────────────────────────────────────────
    path("sales-orders/", SalesOrderListCreateView.as_view(), name="so-list-create"),
    path("sales-orders/<uuid:pk>/", SalesOrderDetailView.as_view(), name="so-detail"),
    path(
        "sales-orders/<uuid:pk>/confirm/",
        ConfirmSalesOrderView.as_view(),
        name="so-confirm",
    ),
    # ── Delivery Notes ────────────────────────────────────────────────────────
    path(
        "delivery-notes/", DeliveryNoteListCreateView.as_view(), name="dn-list-create"
    ),
    path(
        "delivery-notes/<uuid:pk>/", DeliveryNoteDetailView.as_view(), name="dn-detail"
    ),
    path(
        "delivery-notes/<uuid:pk>/validate/",
        ValidateDeliveryNoteView.as_view(),
        name="dn-validate",
    ),
    # ── Sales Invoices ────────────────────────────────────────────────────────
    path(
        "sales-invoices/", SalesInvoiceListCreateView.as_view(), name="si-list-create"
    ),
    path(
        "sales-invoices/<uuid:pk>/", SalesInvoiceDetailView.as_view(), name="si-detail"
    ),
    path(
        "sales-invoices/<uuid:pk>/post/", PostSalesInvoiceView.as_view(), name="si-post"
    ),
    # ── Payments ──────────────────────────────────────────────────────────────
    path("payments/", PaymentListCreateView.as_view(), name="payment-list-create"),
    path("payments/<uuid:pk>/", PaymentDetailView.as_view(), name="payment-detail"),
    path(
        "payments/<uuid:pk>/confirm/",
        ConfirmPaymentView.as_view(),
        name="payment-confirm",
    ),
    # ── Stock ─────────────────────────────────────────────────────────────────
    path("stock-moves/", StockMoveListView.as_view(), name="stock-move-list"),
]
