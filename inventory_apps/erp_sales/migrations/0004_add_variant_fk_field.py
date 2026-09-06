import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Phase 1 of 3 — see erp_inventory's 0003/0004/0005 for the full pattern
    this mirrors: repointing SaleOrderLine.product from ProductTemplate to
    ProductVariant. This phase only adds a nullable column."""

    dependencies = [
        ("erp_sales", "0003_saleorder_salesperson"),
        ("erp_base", "0013_backfill_default_variants"),
    ]

    operations = [
        migrations.AddField(
            model_name="saleorderline",
            name="product_variant",
            field=models.ForeignKey(
                null=True, blank=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="+", to="erp_base.productvariant",
            ),
        ),
    ]
