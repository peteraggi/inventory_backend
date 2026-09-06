import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Phase 3 of 3: drop the old ProductTemplate FK, promote the backfilled
    `product_variant` column into its place as `product`. Safe now that
    phase 2 has populated `product_variant` on every row."""

    dependencies = [
        ("erp_inventory", "0004_backfill_variant_fk_fields"),
    ]

    operations = [
        # unique_together referencing the old "product" field must be
        # cleared before that field can be removed.
        migrations.AlterUniqueTogether(name="stocklot", unique_together=set()),
        migrations.AlterUniqueTogether(name="stockquant", unique_together=set()),
        migrations.AlterUniqueTogether(name="reorderingrule", unique_together=set()),

        migrations.RemoveField(model_name="stocklot", name="product"),
        migrations.RemoveField(model_name="stockmove", name="product"),
        migrations.RemoveField(model_name="stockquant", name="product"),
        migrations.RemoveField(model_name="stockinventoryadjustmentline", name="product"),
        migrations.RemoveField(model_name="reorderingrule", name="product"),

        migrations.RenameField(model_name="stocklot", old_name="product_variant", new_name="product"),
        migrations.RenameField(model_name="stockmove", old_name="product_variant", new_name="product"),
        migrations.RenameField(model_name="stockquant", old_name="product_variant", new_name="product"),
        migrations.RenameField(model_name="stockinventoryadjustmentline", old_name="product_variant", new_name="product"),
        migrations.RenameField(model_name="reorderingrule", old_name="product_variant", new_name="product"),

        migrations.AlterField(
            model_name="stocklot", name="product",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lots", to="erp_base.productvariant"),
        ),
        migrations.AlterField(
            model_name="stockmove", name="product",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="stock_moves", to="erp_base.productvariant"),
        ),
        migrations.AlterField(
            model_name="stockquant", name="product",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="quants", to="erp_base.productvariant"),
        ),
        migrations.AlterField(
            model_name="stockinventoryadjustmentline", name="product",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="adjustment_lines", to="erp_base.productvariant"),
        ),
        migrations.AlterField(
            model_name="reorderingrule", name="product",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="reordering_rules", to="erp_base.productvariant"),
        ),

        migrations.AlterUniqueTogether(name="stocklot", unique_together={("name", "product")}),
        migrations.AlterUniqueTogether(name="stockquant", unique_together={("product", "location", "lot")}),
        migrations.AlterUniqueTogether(name="reorderingrule", unique_together={("product", "location")}),

        migrations.AlterModelOptions(
            name="stockquant",
            options={"ordering": ["product__product_template__name"]},
        ),
        migrations.AlterModelOptions(
            name="reorderingrule",
            options={"ordering": ["product__product_template__name"]},
        ),
    ]
