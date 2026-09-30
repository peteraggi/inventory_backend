import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("erp_accounting", "0005_backfill_variant_fk_field"),
    ]

    operations = [
        migrations.RemoveField(model_name="accountmoveline", name="product"),
        migrations.RenameField(model_name="accountmoveline", old_name="product_variant", new_name="product"),
        migrations.AlterField(
            model_name="accountmoveline", name="product",
            field=models.ForeignKey(
                null=True, blank=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="move_lines", to="erp_base.productvariant",
            ),
        ),
    ]
