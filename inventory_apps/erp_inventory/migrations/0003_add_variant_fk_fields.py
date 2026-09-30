import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Phase 1 of 3 for repointing product FKs from ProductTemplate to
    ProductVariant (see erp_base.ProductVariant / ProductVariantService).
    This phase only ADDS a new nullable column per model — always safe
    regardless of existing data. Phase 2 backfills it, phase 3 drops the
    old column and renames this one into its place."""

    dependencies = [
        ("erp_inventory", "0002_alter_stockinventoryadjustment_date"),
        ("erp_base", "0013_backfill_default_variants"),
    ]

    operations = [
        migrations.AddField(
            model_name="stocklot",
            name="product_variant",
            field=models.ForeignKey(
                null=True, blank=True, on_delete=django.db.models.deletion.CASCADE,
                related_name="+", to="erp_base.productvariant",
            ),
        ),
        migrations.AddField(
            model_name="stockmove",
            name="product_variant",
            field=models.ForeignKey(
                null=True, blank=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="+", to="erp_base.productvariant",
            ),
        ),
        migrations.AddField(
            model_name="stockquant",
            name="product_variant",
            field=models.ForeignKey(
                null=True, blank=True, on_delete=django.db.models.deletion.CASCADE,
                related_name="+", to="erp_base.productvariant",
            ),
        ),
        migrations.AddField(
            model_name="stockinventoryadjustmentline",
            name="product_variant",
            field=models.ForeignKey(
                null=True, blank=True, on_delete=django.db.models.deletion.CASCADE,
                related_name="+", to="erp_base.productvariant",
            ),
        ),
        migrations.AddField(
            model_name="reorderingrule",
            name="product_variant",
            field=models.ForeignKey(
                null=True, blank=True, on_delete=django.db.models.deletion.CASCADE,
                related_name="+", to="erp_base.productvariant",
            ),
        ),
    ]
