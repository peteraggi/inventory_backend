"""
erp_base/services.py — Seed data and master data helpers.
"""
from decimal import Decimal
from itertools import product as cartesian_product


class ProductVariantService:
    """Every template must always have >=1 active ProductVariant — that's
    the row every stock quant/move and sale/purchase/POS order line actually
    references (Odoo's product.product), never the template directly. The
    "default" variant is the one with no attribute_values at all; it's what
    a template gets the moment it's created, before any attributes exist."""

    @classmethod
    def ensure_default_variant(cls, product_template):
        """Guarantees the template has an active variant. No-op if one
        already exists (default or a real combination); reactivates an
        archived default rather than creating a duplicate."""
        from inventory_apps.erp_base.models import ProductVariant

        if product_template.variants.filter(active=True).exists():
            return
        default = product_template.variants.filter(attribute_values__isnull=True).first()
        if default:
            if not default.active:
                default.active = True
                default.save(update_fields=["active"])
            return
        ProductVariant.objects.create(product_template=product_template)

    @classmethod
    def regenerate_variants(cls, product_template):
        """Recomputes `product_template.variants` from its current attribute
        lines. Combinations that already exist as an (active or archived)
        variant are reused/reactivated rather than recreated, so barcodes,
        price extras and stock history survive edits to the attribute lines.
        Combinations no longer possible are archived, never deleted."""
        from django.db import transaction
        from inventory_apps.erp_base.models import ProductVariant

        lines = list(
            product_template.attribute_lines.prefetch_related("values").all()
        )

        with transaction.atomic():
            existing = {
                frozenset(v.attribute_values.values_list("id", flat=True)): v
                for v in product_template.variants.all()
            }

            if not lines:
                # No attributes → fall back to the single default variant,
                # archiving any real combinations left over from before.
                for key, variant in existing.items():
                    if key and variant.active:
                        variant.active = False
                        variant.save(update_fields=["active"])
                cls.ensure_default_variant(product_template)
                return

            value_sets = [list(line.values.all()) for line in lines]
            # A line with no values selected yet can't form any combination.
            if any(len(values) == 0 for values in value_sets):
                return

            desired_combos = list(cartesian_product(*value_sets))
            desired_keys = set()

            for combo in desired_combos:
                key = frozenset(v.id for v in combo)
                desired_keys.add(key)
                variant = existing.get(key)
                if variant is None:
                    variant = ProductVariant.objects.create(product_template=product_template)
                    variant.attribute_values.set(combo)
                elif not variant.active:
                    variant.active = True
                    variant.save(update_fields=["active"])

            # Real combinations now exist, so the attribute-less default
            # variant (key == empty frozenset) is retired along with any
            # combination that's no longer possible.
            for key, variant in existing.items():
                if key not in desired_keys and variant.active:
                    variant.active = False
                    variant.save(update_fields=["active"])


class SetupService:

    @classmethod
    def seed_default_data(cls):
        """Idempotent: creates currency, company, COA stub, journals, payment terms, UOM."""
        from django.utils import timezone
        from inventory_apps.erp_base.models import (
            Currency, CurrencyRate, Company, UomCategory, UnitOfMeasure, TaxGroup, Tax,
            PaymentTerm, PaymentTermLine,
        )
        from inventory_apps.erp_accounting.models import AccountAccount, AccountJournal

        # Currency
        ngn, _ = Currency.objects.get_or_create(
            code="NGN",
            defaults={"name": "Nigerian Naira", "symbol": "₦", "rate": Decimal("1.000000")},
        )
        usd, _ = Currency.objects.get_or_create(
            code="USD",
            defaults={"name": "US Dollar", "symbol": "$", "rate": Decimal("1600.000000")},
        )
        ugx, _ = Currency.objects.get_or_create(
            code="UGX",
            defaults={"name": "Ugandan Shilling", "symbol": "USh", "rate": Decimal("1.000000")},
        )
        for currency in (ngn, usd, ugx):
            if not currency.rates.exists():
                CurrencyRate.objects.create(
                    currency=currency, rate=currency.rate, rate_date=timezone.now().date(),
                )

        # Company
        company, _ = Company.objects.get_or_create(
            name="My Company",
            defaults={
                "currency": ngn,
                "country": "Nigeria",
            },
        )

        # UOM categories
        unit_cat, _ = UomCategory.objects.get_or_create(name="Unit")
        weight_cat, _ = UomCategory.objects.get_or_create(name="Weight")
        vol_cat, _ = UomCategory.objects.get_or_create(name="Volume")

        # UOMs
        for uom_data in [
            {"name": "Units", "category": unit_cat, "uom_type": "reference"},
            {"name": "Dozen", "category": unit_cat, "uom_type": "bigger", "factor": Decimal("12.000000")},
            {"name": "kg", "category": weight_cat, "uom_type": "reference"},
            {"name": "g", "category": weight_cat, "uom_type": "smaller", "factor": Decimal("1000.000000")},
            {"name": "L", "category": vol_cat, "uom_type": "reference"},
            {"name": "mL", "category": vol_cat, "uom_type": "smaller", "factor": Decimal("1000.000000")},
        ]:
            UnitOfMeasure.objects.get_or_create(
                name=uom_data["name"], category=uom_data["category"],
                defaults={k: v for k, v in uom_data.items() if k not in ("name", "category")},
            )

        # Tax group + VAT
        tg, _ = TaxGroup.objects.get_or_create(name="Taxes")
        vat, _ = Tax.objects.get_or_create(
            name="VAT 7.5%",
            defaults={
                "type_tax_use": "sale",
                "amount_type": "percent",
                "amount": Decimal("7.5000"),
                "tax_group": tg,
            },
        )
        vat_p, _ = Tax.objects.get_or_create(
            name="VAT 7.5% (Purchase)",
            defaults={
                "type_tax_use": "purchase",
                "amount_type": "percent",
                "amount": Decimal("7.5000"),
                "tax_group": tg,
            },
        )

        # Payment terms
        immediate, _ = PaymentTerm.objects.get_or_create(name="Immediate Payment")
        if not immediate.lines.exists():
            PaymentTermLine.objects.create(payment_term=immediate, value="balance", days=0)

        net30, _ = PaymentTerm.objects.get_or_create(name="Net 30 Days")
        if not net30.lines.exists():
            PaymentTermLine.objects.create(payment_term=net30, value="balance", days=30)

        # Chart of accounts (minimal)
        coa_entries = [
            ("1000", "Cash", "asset_cash"),
            ("1100", "Accounts Receivable", "asset_receivable"),
            ("1200", "Inventory", "asset_current"),
            ("1500", "Fixed Assets", "asset_fixed"),
            ("2000", "Accounts Payable", "liability_payable"),
            ("2100", "VAT Payable", "liability_current"),
            ("3000", "Capital", "equity"),
            ("3100", "Retained Earnings", "equity_unaffected"),
            ("4000", "Sales Revenue", "income"),
            ("4100", "Other Income", "income_other"),
            ("5000", "Cost of Goods Sold", "expense_direct_cost"),
            ("6000", "Operating Expenses", "expense"),
            ("6100", "Depreciation", "expense_depreciation"),
        ]
        for code, name, acct_type in coa_entries:
            AccountAccount.objects.get_or_create(
                code=code,
                defaults={"name": name, "account_type": acct_type},
            )

        # Journals
        cash_acct = AccountAccount.objects.filter(code="1000").first()
        ar_acct = AccountAccount.objects.filter(code="1100").first()
        ap_acct = AccountAccount.objects.filter(code="2000").first()
        sales_acct = AccountAccount.objects.filter(code="4000").first()
        cogs_acct = AccountAccount.objects.filter(code="5000").first()

        journals = [
            {"name": "Customer Invoices", "code": "INV", "journal_type": "sale", "default_account": sales_acct},
            {"name": "Vendor Bills", "code": "BILL", "journal_type": "purchase", "default_account": ap_acct},
            {"name": "Cash", "code": "CSH", "journal_type": "cash", "default_account": cash_acct},
            {"name": "Bank", "code": "BNK", "journal_type": "bank", "default_account": cash_acct},
            {"name": "Miscellaneous", "code": "MISC", "journal_type": "general", "default_account": None},
        ]
        for jdata in journals:
            AccountJournal.objects.get_or_create(
                code=jdata["code"],
                defaults={
                    "name": jdata["name"],
                    "journal_type": jdata["journal_type"],
                    "default_account": jdata["default_account"],
                    "company": company,
                },
            )

        # Default warehouse
        from inventory_apps.erp_inventory.models import Warehouse, StockLocation
        wh, created = Warehouse.objects.get_or_create(
            short_name="WH",
            defaults={"name": "Main Warehouse", "company": company},
        )

        # Global locations (shared across warehouses)
        for usage, name in [("supplier", "Vendors"), ("customer", "Customers"), ("inventory", "Inventory Adjustments")]:
            StockLocation.objects.get_or_create(
                name=name, usage=usage,
                defaults={"active": True},
            )

        # Tenant roles (Settings → Roles / Permissions) — fixed presets with a
        # sensible default permission matrix per inventory_apps.erp_base.rbac_constants.
        from inventory_apps.pos_app.models import Role
        from inventory_apps.erp_base.rbac_constants import DEFAULT_ROLE_PERMISSIONS, DEFAULT_ROLE_DESCRIPTIONS

        for role_name, display_name in Role.ROLE_CHOICES:
            Role.objects.get_or_create(
                name=role_name,
                defaults={
                    "display_name": display_name,
                    "description": DEFAULT_ROLE_DESCRIPTIONS.get(role_name, ""),
                    "permissions": DEFAULT_ROLE_PERMISSIONS.get(role_name, {}),
                },
            )

        # Tenant modules (Settings → Modules) — everything on by default.
        from inventory_apps.erp_base.models import TenantModule

        for key, name in TenantModule.MODULE_CHOICES:
            TenantModule.objects.get_or_create(
                key=key,
                defaults={"name": name, "enabled": True},
            )

        return {
            "company": str(company.id),
            "currency": ngn.code,
            "warehouse": str(wh.id),
        }
