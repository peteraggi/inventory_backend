import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("erp_pos", "0002_posorderline_tax_exempt"),
        ("erp_base", "0013_backfill_default_variants"),
    ]

    operations = [
        migrations.AddField(
            model_name="posorderline",
            name="product_variant",
            field=models.ForeignKey(
                null=True, blank=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="+", to="erp_base.productvariant",
            ),
        ),
    ]
