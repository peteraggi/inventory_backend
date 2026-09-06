import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("erp_purchase", "0004_purchaseorder_active"),
        ("erp_base", "0013_backfill_default_variants"),
    ]

    operations = [
        migrations.AddField(
            model_name="purchaseorderline",
            name="product_variant",
            field=models.ForeignKey(
                null=True, blank=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="+", to="erp_base.productvariant",
            ),
        ),
    ]
