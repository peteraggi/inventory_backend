import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("erp_accounting", "0003_accountmoveline_taxes"),
        ("erp_base", "0013_backfill_default_variants"),
    ]

    operations = [
        migrations.AddField(
            model_name="accountmoveline",
            name="product_variant",
            field=models.ForeignKey(
                null=True, blank=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="+", to="erp_base.productvariant",
            ),
        ),
    ]
