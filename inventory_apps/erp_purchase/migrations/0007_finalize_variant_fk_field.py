import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("erp_purchase", "0006_backfill_variant_fk_field"),
    ]

    operations = [
        migrations.RemoveField(model_name="purchaseorderline", name="product"),
        migrations.RenameField(model_name="purchaseorderline", old_name="product_variant", new_name="product"),
        migrations.AlterField(
            model_name="purchaseorderline", name="product",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="purchase_lines", to="erp_base.productvariant"),
        ),
    ]
