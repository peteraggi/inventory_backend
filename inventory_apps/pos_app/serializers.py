# pos_app/serializers.py

from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from decimal import Decimal

from .models import (
    Store,
    Role,
    Category,
    Product,
    Invoice,
    InvoiceItem,
    SyncLog,
    DailySales,
    Contact,
    Account,
    Journal,
    JournalEntry,
    JournalEntryLine,
    PurchaseOrder,
    PurchaseOrderLine,
    GoodsReceipt,
    GoodsReceiptLine,
    VendorBill,
    VendorBillLine,
    SalesOrder,
    SalesOrderLine,
    DeliveryNote,
    DeliveryNoteLine,
    SalesInvoice,
    SalesInvoiceLine,
    Payment,
    StockMove,
)
from ..authentication.models import User

# ─── STORE & ROLE ─────────────────────────────────────────────────────────────


class StoreSerializer(serializers.ModelSerializer):
    user_count = serializers.SerializerMethodField()
    product_count = serializers.SerializerMethodField()

    class Meta:
        model = Store
        fields = [
            "id",
            "name",
            "code",
            "address",
            "phone",
            "email",
            "tax_rate",
            "currency",
            "is_active",
            "user_count",
            "product_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_user_count(self, obj):
        return obj.users.filter(is_active=True).count()

    def get_product_count(self, obj):
        return obj.products.filter(is_active=True).count()


class StoreListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Store
        fields = ["id", "name", "code"]


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ["id", "name", "display_name", "description", "permissions"]
        read_only_fields = ["id"]


class UserProfileSerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField(source="id", read_only=True)
    store_name = serializers.CharField(source="store.name", read_only=True)
    store_id = serializers.UUIDField(source="store.id", read_only=True)
    role_name = serializers.CharField(source="role.name", read_only=True)

    class Meta:
        model = User
        fields = [
            "user_id",
            "username",
            "name",
            "email",
            "phone",
            "bio",
            "store_id",
            "store_name",
            "role_name",
            "is_verified",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "user_id",
            "email",
            "username",
            "is_verified",
            "store_id",
            "store_name",
            "role_name",
            "created_at",
            "updated_at",
        ]


# ─── CATEGORY ─────────────────────────────────────────────────────────────────


class CategorySerializer(serializers.ModelSerializer):
    product_count = serializers.SerializerMethodField()
    income_account_name = serializers.CharField(
        source="income_account.name", read_only=True
    )
    cogs_account_name = serializers.CharField(
        source="cogs_account.name", read_only=True
    )
    inventory_account_name = serializers.CharField(
        source="inventory_account.name", read_only=True
    )

    class Meta:
        model = Category
        fields = [
            "id",
            "name",
            "description",
            "parent",
            "cost_method",
            "income_account",
            "income_account_name",
            "cogs_account",
            "cogs_account_name",
            "inventory_account",
            "inventory_account_name",
            "product_count",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_product_count(self, obj):
        return obj.products.filter(is_active=True).count()

    def validate(self, attrs):
        request = self.context.get("request")
        if request and request.user:
            attrs["store"] = request.user.store
        return attrs


# ─── PRODUCT ──────────────────────────────────────────────────────────────────


class ProductSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    is_low_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "code",
            "description",
            "category",
            "category_name",
            "price",
            "cost",
            "avg_cost",
            "standard_cost",
            "stock",
            "stock_value",
            "low_stock_threshold",
            "is_low_stock",
            "barcode",
            "image_url",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "is_low_stock",
            "avg_cost",
            "stock_value",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        request = self.context.get("request")
        if request and request.user:
            attrs["store"] = request.user.store
            attrs["created_by"] = request.user
        category = attrs.get("category")
        if category and category.store != attrs.get("store"):
            raise ValidationError({"category": "Category must belong to your store"})
        return attrs

    def validate_price(self, value):
        if value <= 0:
            raise ValidationError("Price must be greater than 0")
        return value


class ProductListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ["id", "name", "code", "price", "stock", "is_active"]


# ─── POS INVOICE ──────────────────────────────────────────────────────────────


class InvoiceItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceItem
        fields = [
            "id",
            "product",
            "product_name",
            "product_code",
            "quantity",
            "price",
            "total",
            "created_at",
        ]
        read_only_fields = ["id", "total", "created_at"]

    def validate(self, attrs):
        product = attrs.get("product")
        quantity = attrs.get("quantity")
        if product:
            attrs["product_name"] = product.name
            attrs["product_code"] = product.code
            attrs["price"] = attrs.get("price", product.price)
        if product and quantity:
            if product.stock < quantity:
                raise ValidationError(
                    {"quantity": f"Insufficient stock. Available: {product.stock}"}
                )
        return attrs


class InvoiceSerializer(serializers.ModelSerializer):
    items = InvoiceItemSerializer(many=True, read_only=False)
    salesperson_name = serializers.CharField(source="salesperson.name", read_only=True)
    store_name = serializers.CharField(source="store.name", read_only=True)

    class Meta:
        model = Invoice
        fields = [
            "id",
            "invoice_number",
            "salesperson",
            "salesperson_name",
            "store_name",
            "items",
            "subtotal",
            "tax",
            "discount",
            "total",
            "customer_name",
            "customer_phone",
            "customer_email",
            "notes",
            "sync_status",
            "synced_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "salesperson_name",
            "store_name",
            "subtotal",
            "tax",
            "total",
            "synced_at",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        request = self.context.get("request")
        if request and request.user:
            attrs["store"] = request.user.store
            attrs["salesperson"] = request.user
        if not attrs.get("invoice_number"):
            import time

            attrs["invoice_number"] = f"INV-{int(time.time())}"
        return attrs

    def create(self, validated_data):
        items_data = validated_data.pop("items")
        invoice = Invoice.objects.create(**validated_data)
        for item_data in items_data:
            product = item_data["product"]
            InvoiceItem.objects.create(invoice=invoice, **item_data)
            product.stock -= item_data["quantity"]
            product.save()
        invoice.calculate_totals()
        invoice.save()
        return invoice


class InvoiceListSerializer(serializers.ModelSerializer):
    salesperson_name = serializers.CharField(source="salesperson.name", read_only=True)
    items = InvoiceItemSerializer(many=True, read_only=True)
    item_count = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            "id",
            "invoice_number",
            "salesperson",
            "salesperson_name",
            "items",
            "subtotal",
            "tax",
            "discount",
            "total",
            "item_count",
            "sync_status",
            "created_at",
        ]

    def get_item_count(self, obj):
        return obj.items.count()


class BulkInvoiceItemSerializer(serializers.Serializer):
    product = serializers.UUIDField()
    product_name = serializers.CharField(max_length=255)
    product_code = serializers.CharField(max_length=100)
    quantity = serializers.IntegerField(min_value=1)
    price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0.01)
    total = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)

    def validate_product(self, value):
        request = self.context.get("request")
        try:
            return Product.objects.get(
                id=value, store=request.user.store, is_active=True
            )
        except Product.DoesNotExist:
            raise ValidationError(f'"{value}" is not a valid UUID.')

    def validate(self, attrs):
        if "total" not in attrs or attrs["total"] is None:
            attrs["total"] = attrs["quantity"] * attrs["price"]
        return attrs


class BulkInvoiceSerializer(serializers.Serializer):
    id = serializers.CharField(required=False)
    createdAt = serializers.DateTimeField(required=False)
    invoice_number = serializers.CharField(max_length=100)
    salesperson = serializers.UUIDField()
    salespersonName = serializers.CharField(required=False)
    subtotal = serializers.DecimalField(max_digits=12, decimal_places=2)
    tax = serializers.DecimalField(max_digits=12, decimal_places=2)
    discount = serializers.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00")
    )
    total = serializers.DecimalField(max_digits=12, decimal_places=2)
    customer_name = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )
    customer_phone = serializers.CharField(
        max_length=50, required=False, allow_blank=True
    )
    customer_email = serializers.EmailField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    syncStatus = serializers.CharField(required=False)
    items = BulkInvoiceItemSerializer(many=True)

    def validate_salesperson(self, value):
        request = self.context.get("request")
        try:
            return User.objects.get(id=value, store=request.user.store, is_active=True)
        except User.DoesNotExist:
            raise ValidationError(f'"{value}" is not a valid UUID.')

    def validate_invoice_number(self, value):
        request = self.context.get("request")
        if Invoice.objects.filter(
            invoice_number=value, store=request.user.store
        ).exists():
            raise ValidationError(f'Invoice with number "{value}" already exists.')
        return value

    def validate(self, attrs):
        if not attrs.get("items"):
            raise ValidationError({"items": "At least one item is required."})
        for item_data in attrs["items"]:
            product = item_data["product"]
            quantity = item_data["quantity"]
            if product.stock < quantity:
                raise ValidationError(
                    {
                        "items": f"Insufficient stock for {product.code}. Available: {product.stock}, Requested: {quantity}"
                    }
                )
        return attrs


class BulkInvoiceSyncSerializer(serializers.Serializer):
    invoices = BulkInvoiceSerializer(many=True)

    def create(self, validated_data):
        invoices_data = validated_data.get("invoices", [])
        synced_invoices = []
        failed_invoices = []
        request = self.context.get("request")
        store = request.user.store

        for invoice_data in invoices_data:
            try:
                items_data = invoice_data.pop("items")
                invoice_data.pop("id", None)
                invoice_data.pop("createdAt", None)
                invoice_data.pop("salespersonName", None)
                invoice_data.pop("syncStatus", None)
                invoice = Invoice.objects.create(
                    store=store,
                    sync_status="SYNCED",
                    synced_at=timezone.now(),
                    **invoice_data,
                )
                for item_data in items_data:
                    product = item_data["product"]
                    InvoiceItem.objects.create(
                        invoice=invoice,
                        product=product,
                        product_name=item_data["product_name"],
                        product_code=item_data["product_code"],
                        quantity=item_data["quantity"],
                        price=item_data["price"],
                        total=item_data["total"],
                    )
                    product.stock -= item_data["quantity"]
                    product.save()
                synced_invoices.append(invoice)
            except ValidationError as e:
                failed_invoices.append(
                    {
                        "invoice_number": invoice_data.get("invoice_number", "Unknown"),
                        "errors": e.detail if hasattr(e, "detail") else str(e),
                    }
                )
            except Exception as e:
                failed_invoices.append(
                    {
                        "invoice_number": invoice_data.get("invoice_number", "Unknown"),
                        "errors": {"error": str(e)},
                    }
                )

        return {
            "synced": len(synced_invoices),
            "failed": len(failed_invoices),
            "failed_invoices": failed_invoices,
        }


# ─── ANALYTICS ────────────────────────────────────────────────────────────────


class DashboardStatsSerializer(serializers.Serializer):
    today_sales = serializers.DecimalField(max_digits=12, decimal_places=2)
    invoice_count = serializers.IntegerField()
    top_product = serializers.CharField()
    active_salespeople = serializers.IntegerField()
    week_sales = serializers.DecimalField(max_digits=12, decimal_places=2)
    month_sales = serializers.DecimalField(max_digits=12, decimal_places=2)
    low_stock_products = serializers.IntegerField()


class SalesReportSerializer(serializers.Serializer):
    salesperson_id = serializers.UUIDField()
    salesperson_name = serializers.CharField()
    total_sales = serializers.DecimalField(max_digits=12, decimal_places=2)
    invoice_count = serializers.IntegerField()
    average_sale = serializers.DecimalField(max_digits=12, decimal_places=2)


class ProductReportSerializer(serializers.Serializer):
    product_id = serializers.UUIDField()
    product_name = serializers.CharField()
    product_code = serializers.CharField()
    quantity_sold = serializers.IntegerField()
    total_revenue = serializers.DecimalField(max_digits=12, decimal_places=2)


class SyncLogSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.name", read_only=True)

    class Meta:
        model = SyncLog
        fields = [
            "id",
            "user_name",
            "sync_type",
            "status",
            "items_synced",
            "items_failed",
            "error_message",
            "started_at",
            "completed_at",
        ]
        read_only_fields = ["id", "user_name", "started_at", "completed_at"]


# ─── CONTACTS ─────────────────────────────────────────────────────────────────


class ContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = [
            "id",
            "name",
            "contact_type",
            "email",
            "phone",
            "address",
            "city",
            "state",
            "country",
            "tax_id",
            "payment_terms_days",
            "credit_limit",
            "notes",
            "is_active",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class ContactListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = ["id", "name", "contact_type", "email", "phone", "is_active"]


# ─── ACCOUNTS & JOURNALS ──────────────────────────────────────────────────────


class AccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Account
        fields = [
            "id",
            "code",
            "name",
            "account_type",
            "normal_balance",
            "parent",
            "description",
            "is_active",
            "is_system",
        ]
        read_only_fields = ["id", "normal_balance", "is_system"]


class JournalSerializer(serializers.ModelSerializer):
    default_debit_account_name = serializers.CharField(
        source="default_debit_account.name", read_only=True
    )
    default_credit_account_name = serializers.CharField(
        source="default_credit_account.name", read_only=True
    )

    class Meta:
        model = Journal
        fields = [
            "id",
            "name",
            "code",
            "journal_type",
            "default_debit_account",
            "default_debit_account_name",
            "default_credit_account",
            "default_credit_account_name",
            "is_active",
        ]
        read_only_fields = ["id"]


class JournalEntryLineSerializer(serializers.ModelSerializer):
    account_code = serializers.CharField(source="account.code", read_only=True)
    account_name = serializers.CharField(source="account.name", read_only=True)
    partner_name = serializers.CharField(source="partner.name", read_only=True)

    class Meta:
        model = JournalEntryLine
        fields = [
            "id",
            "account",
            "account_code",
            "account_name",
            "description",
            "debit",
            "credit",
            "partner",
            "partner_name",
        ]
        read_only_fields = ["id"]


class JournalEntrySerializer(serializers.ModelSerializer):
    lines = JournalEntryLineSerializer(many=True, read_only=True)
    journal_name = serializers.CharField(source="journal.name", read_only=True)

    class Meta:
        model = JournalEntry
        fields = [
            "id",
            "journal",
            "journal_name",
            "reference",
            "date",
            "memo",
            "status",
            "total_debit",
            "total_credit",
            "source_type",
            "source_id",
            "created_at",
            "posted_at",
            "lines",
        ]
        read_only_fields = [
            "id",
            "total_debit",
            "total_credit",
            "status",
            "created_at",
            "posted_at",
        ]


# ─── STOCK MOVE ───────────────────────────────────────────────────────────────


class StockMoveSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_code = serializers.CharField(source="product.code", read_only=True)

    class Meta:
        model = StockMove
        fields = [
            "id",
            "product",
            "product_code",
            "product_name",
            "move_type",
            "quantity",
            "unit_cost",
            "valuation_amount",
            "source_type",
            "source_id",
            "note",
            "date",
        ]
        read_only_fields = ["id", "valuation_amount"]


# ─── PURCHASE ─────────────────────────────────────────────────────────────────


class PurchaseOrderLineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_code = serializers.CharField(source="product.code", read_only=True)
    pending_qty = serializers.DecimalField(
        max_digits=14, decimal_places=4, read_only=True
    )

    class Meta:
        model = PurchaseOrderLine
        fields = [
            "id",
            "product",
            "product_code",
            "product_name",
            "description",
            "quantity",
            "received_qty",
            "pending_qty",
            "unit_cost",
            "tax_rate",
            "subtotal",
            "tax_amount",
            "total",
        ]
        read_only_fields = ["id", "received_qty", "subtotal", "tax_amount", "total"]


class PurchaseOrderSerializer(serializers.ModelSerializer):
    lines = PurchaseOrderLineSerializer(many=True)
    vendor_name = serializers.CharField(source="vendor.name", read_only=True)
    created_by_name = serializers.CharField(source="created_by.name", read_only=True)

    class Meta:
        model = PurchaseOrder
        fields = [
            "id",
            "po_number",
            "vendor",
            "vendor_name",
            "status",
            "order_date",
            "expected_date",
            "notes",
            "subtotal",
            "tax_amount",
            "discount",
            "total",
            "created_by",
            "created_by_name",
            "approved_by",
            "created_at",
            "updated_at",
            "lines",
        ]
        read_only_fields = [
            "id",
            "po_number",
            "status",
            "subtotal",
            "tax_amount",
            "total",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data):
        lines_data = validated_data.pop("lines")
        request = self.context["request"]
        store = request.user.store
        po = PurchaseOrder.objects.create(
            store=store,
            po_number=_generate_number("PO", store),
            created_by=request.user,
            **validated_data,
        )
        for line in lines_data:
            PurchaseOrderLine.objects.create(purchase_order=po, **line)
        po.recalculate_totals()
        return po


class PurchaseOrderListSerializer(serializers.ModelSerializer):
    vendor_name = serializers.CharField(source="vendor.name", read_only=True)

    class Meta:
        model = PurchaseOrder
        fields = [
            "id",
            "po_number",
            "vendor_name",
            "status",
            "order_date",
            "total",
            "created_at",
        ]


# ─── GOODS RECEIPT ────────────────────────────────────────────────────────────


class GoodsReceiptLineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_code = serializers.CharField(source="product.code", read_only=True)
    total_value = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True
    )

    class Meta:
        model = GoodsReceiptLine
        fields = [
            "id",
            "purchase_order_line",
            "product",
            "product_code",
            "product_name",
            "ordered_qty",
            "received_qty",
            "unit_cost",
            "total_value",
        ]
        read_only_fields = ["id", "total_value"]


class GoodsReceiptSerializer(serializers.ModelSerializer):
    lines = GoodsReceiptLineSerializer(many=True)
    po_number = serializers.CharField(source="purchase_order.po_number", read_only=True)
    vendor_name = serializers.CharField(
        source="purchase_order.vendor.name", read_only=True
    )

    class Meta:
        model = GoodsReceipt
        fields = [
            "id",
            "receipt_number",
            "purchase_order",
            "po_number",
            "vendor_name",
            "received_date",
            "status",
            "notes",
            "validated_by",
            "validated_at",
            "created_at",
            "lines",
        ]
        read_only_fields = [
            "id",
            "receipt_number",
            "status",
            "validated_by",
            "validated_at",
            "created_at",
        ]

    def create(self, validated_data):
        lines_data = validated_data.pop("lines")
        request = self.context["request"]
        store = request.user.store
        receipt = GoodsReceipt.objects.create(
            store=store, receipt_number=_generate_number("GR", store), **validated_data
        )
        for line in lines_data:
            GoodsReceiptLine.objects.create(goods_receipt=receipt, **line)
        return receipt


class GoodsReceiptListSerializer(serializers.ModelSerializer):
    po_number = serializers.CharField(source="purchase_order.po_number", read_only=True)
    vendor_name = serializers.CharField(
        source="purchase_order.vendor.name", read_only=True
    )

    class Meta:
        model = GoodsReceipt
        fields = [
            "id",
            "receipt_number",
            "po_number",
            "vendor_name",
            "received_date",
            "status",
        ]


# ─── VENDOR BILL ──────────────────────────────────────────────────────────────


class VendorBillLineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    account_name = serializers.CharField(source="account.name", read_only=True)

    class Meta:
        model = VendorBillLine
        fields = [
            "id",
            "product",
            "product_name",
            "description",
            "quantity",
            "unit_cost",
            "tax_rate",
            "subtotal",
            "tax_amount",
            "total",
            "account",
            "account_name",
        ]
        read_only_fields = ["id", "subtotal", "tax_amount", "total"]


class VendorBillSerializer(serializers.ModelSerializer):
    lines = VendorBillLineSerializer(many=True)
    vendor_name = serializers.CharField(source="vendor.name", read_only=True)
    po_number = serializers.CharField(source="purchase_order.po_number", read_only=True)
    amount_due = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True
    )

    class Meta:
        model = VendorBill
        fields = [
            "id",
            "bill_number",
            "vendor",
            "vendor_name",
            "purchase_order",
            "po_number",
            "bill_date",
            "due_date",
            "status",
            "subtotal",
            "tax_amount",
            "total",
            "amount_paid",
            "amount_due",
            "notes",
            "created_at",
            "lines",
        ]
        read_only_fields = [
            "id",
            "bill_number",
            "status",
            "subtotal",
            "tax_amount",
            "total",
            "amount_paid",
            "created_at",
        ]

    def create(self, validated_data):
        lines_data = validated_data.pop("lines")
        request = self.context["request"]
        store = request.user.store
        bill = VendorBill.objects.create(
            store=store,
            bill_number=_generate_number("BILL", store),
            created_by=request.user,
            **validated_data,
        )
        for line in lines_data:
            VendorBillLine.objects.create(vendor_bill=bill, **line)
        lines = bill.lines.all()
        bill.subtotal = sum(l.subtotal for l in lines)
        bill.tax_amount = sum(l.tax_amount for l in lines)
        bill.total = bill.subtotal + bill.tax_amount
        bill.save(update_fields=["subtotal", "tax_amount", "total"])
        return bill


class VendorBillListSerializer(serializers.ModelSerializer):
    vendor_name = serializers.CharField(source="vendor.name", read_only=True)
    amount_due = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True
    )

    class Meta:
        model = VendorBill
        fields = [
            "id",
            "bill_number",
            "vendor_name",
            "bill_date",
            "due_date",
            "status",
            "total",
            "amount_due",
        ]


# ─── SALES ORDER ──────────────────────────────────────────────────────────────


class SalesOrderLineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_code = serializers.CharField(source="product.code", read_only=True)
    pending_qty = serializers.DecimalField(
        max_digits=14, decimal_places=4, read_only=True
    )

    class Meta:
        model = SalesOrderLine
        fields = [
            "id",
            "product",
            "product_code",
            "product_name",
            "description",
            "quantity",
            "delivered_qty",
            "pending_qty",
            "unit_price",
            "discount_pct",
            "subtotal",
            "total",
        ]
        read_only_fields = ["id", "delivered_qty", "subtotal", "total"]


class SalesOrderSerializer(serializers.ModelSerializer):
    lines = SalesOrderLineSerializer(many=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    salesperson_name = serializers.CharField(source="salesperson.name", read_only=True)

    class Meta:
        model = SalesOrder
        fields = [
            "id",
            "so_number",
            "customer",
            "customer_name",
            "salesperson",
            "salesperson_name",
            "status",
            "order_date",
            "delivery_date",
            "notes",
            "subtotal",
            "tax_amount",
            "discount",
            "total",
            "created_at",
            "updated_at",
            "lines",
        ]
        read_only_fields = [
            "id",
            "so_number",
            "status",
            "subtotal",
            "tax_amount",
            "total",
            "salesperson",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data):
        lines_data = validated_data.pop("lines")
        request = self.context["request"]
        store = request.user.store
        so = SalesOrder.objects.create(
            store=store,
            so_number=_generate_number("SO", store),
            salesperson=request.user,
            **validated_data,
        )
        for line in lines_data:
            SalesOrderLine.objects.create(sales_order=so, **line)
        so.recalculate_totals()
        return so


class SalesOrderListSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name", read_only=True)

    class Meta:
        model = SalesOrder
        fields = [
            "id",
            "so_number",
            "customer_name",
            "status",
            "order_date",
            "total",
            "created_at",
        ]


# ─── DELIVERY NOTE ────────────────────────────────────────────────────────────


class DeliveryNoteLineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_code = serializers.CharField(source="product.code", read_only=True)

    class Meta:
        model = DeliveryNoteLine
        fields = [
            "id",
            "sales_order_line",
            "product",
            "product_code",
            "product_name",
            "ordered_qty",
            "delivered_qty",
        ]
        read_only_fields = ["id"]


class DeliveryNoteSerializer(serializers.ModelSerializer):
    lines = DeliveryNoteLineSerializer(many=True)
    so_number = serializers.CharField(source="sales_order.so_number", read_only=True)
    customer_name = serializers.CharField(
        source="sales_order.customer.name", read_only=True
    )

    class Meta:
        model = DeliveryNote
        fields = [
            "id",
            "delivery_number",
            "sales_order",
            "so_number",
            "customer_name",
            "delivery_date",
            "status",
            "notes",
            "delivered_by",
            "delivered_at",
            "created_at",
            "lines",
        ]
        read_only_fields = [
            "id",
            "delivery_number",
            "status",
            "delivered_by",
            "delivered_at",
            "created_at",
        ]

    def create(self, validated_data):
        lines_data = validated_data.pop("lines")
        request = self.context["request"]
        store = request.user.store
        note = DeliveryNote.objects.create(
            store=store, delivery_number=_generate_number("DN", store), **validated_data
        )
        for line in lines_data:
            DeliveryNoteLine.objects.create(delivery_note=note, **line)
        return note


class DeliveryNoteListSerializer(serializers.ModelSerializer):
    so_number = serializers.CharField(source="sales_order.so_number", read_only=True)
    customer_name = serializers.CharField(
        source="sales_order.customer.name", read_only=True
    )

    class Meta:
        model = DeliveryNote
        fields = [
            "id",
            "delivery_number",
            "so_number",
            "customer_name",
            "delivery_date",
            "status",
        ]


# ─── SALES INVOICE ────────────────────────────────────────────────────────────


class SalesInvoiceLineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_code = serializers.CharField(source="product.code", read_only=True)

    class Meta:
        model = SalesInvoiceLine
        fields = [
            "id",
            "product",
            "product_code",
            "product_name",
            "description",
            "quantity",
            "unit_price",
            "discount_pct",
            "subtotal",
            "total",
            "income_account",
            "cogs_account",
            "cost_at_sale",
        ]
        read_only_fields = [
            "id",
            "subtotal",
            "total",
            "income_account",
            "cogs_account",
            "cost_at_sale",
        ]


class SalesInvoiceSerializer(serializers.ModelSerializer):
    lines = SalesInvoiceLineSerializer(many=True)
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    salesperson_name = serializers.CharField(source="salesperson.name", read_only=True)
    amount_due = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True
    )

    class Meta:
        model = SalesInvoice
        fields = [
            "id",
            "invoice_number",
            "sales_order",
            "customer",
            "customer_name",
            "salesperson",
            "salesperson_name",
            "invoice_date",
            "due_date",
            "status",
            "subtotal",
            "tax_amount",
            "discount",
            "total",
            "amount_paid",
            "amount_due",
            "notes",
            "created_at",
            "updated_at",
            "lines",
        ]
        read_only_fields = [
            "id",
            "invoice_number",
            "status",
            "subtotal",
            "tax_amount",
            "total",
            "amount_paid",
            "salesperson",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data):
        lines_data = validated_data.pop("lines")
        request = self.context["request"]
        store = request.user.store
        inv = SalesInvoice.objects.create(
            store=store,
            invoice_number=_generate_number("INV", store),
            salesperson=request.user,
            **validated_data,
        )
        for line in lines_data:
            SalesInvoiceLine.objects.create(sales_invoice=inv, **line)
        inv.recalculate_totals()
        return inv


class SalesInvoiceListSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    amount_due = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True
    )

    class Meta:
        model = SalesInvoice
        fields = [
            "id",
            "invoice_number",
            "customer_name",
            "status",
            "invoice_date",
            "due_date",
            "total",
            "amount_due",
        ]


# ─── PAYMENT ──────────────────────────────────────────────────────────────────


class PaymentSerializer(serializers.ModelSerializer):
    contact_name = serializers.CharField(source="contact.name", read_only=True)
    invoice_number = serializers.CharField(
        source="sales_invoice.invoice_number", read_only=True
    )
    bill_number = serializers.CharField(
        source="vendor_bill.bill_number", read_only=True
    )

    class Meta:
        model = Payment
        fields = [
            "id",
            "payment_number",
            "payment_type",
            "payment_method",
            "contact",
            "contact_name",
            "amount",
            "date",
            "reference",
            "notes",
            "status",
            "sales_invoice",
            "invoice_number",
            "vendor_bill",
            "bill_number",
            "created_at",
        ]
        read_only_fields = ["id", "payment_number", "status", "created_at"]

    def create(self, validated_data):
        request = self.context["request"]
        store = request.user.store
        return Payment.objects.create(
            store=store,
            payment_number=_generate_number("PAY", store),
            created_by=request.user,
            **validated_data,
        )


# ─── HELPERS ──────────────────────────────────────────────────────────────────


def _generate_number(prefix, store):
    """Generate sequential document number e.g. PO-2026-0001"""
    year = timezone.now().year
    model_map = {
        "PO": (PurchaseOrder, "po_number"),
        "GR": (GoodsReceipt, "receipt_number"),
        "BILL": (VendorBill, "bill_number"),
        "SO": (SalesOrder, "so_number"),
        "DN": (DeliveryNote, "delivery_number"),
        "INV": (SalesInvoice, "invoice_number"),
        "PAY": (Payment, "payment_number"),
    }
    Model, field = model_map[prefix]
    prefix_year = f"{prefix}-{year}-"
    count = (
        Model.objects.filter(
            **{f"{field}__startswith": prefix_year, "store": store}
        ).count()
        + 1
    )
    return f"{prefix_year}{count:04d}"
