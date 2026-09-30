import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("erp_pos", "0004_backfill_variant_fk_field"),
    ]

    operations = [
        migrations.RemoveField(model_name="posorderline", name="product"),
        migrations.RenameField(model_name="posorderline", old_name="product_variant", new_name="product"),
        migrations.AlterField(
            model_name="posorderline", name="product",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="pos_lines", to="erp_base.productvariant"),
        ),
    ]
