import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("erp_sales", "0005_backfill_variant_fk_field"),
    ]

    operations = [
        migrations.RemoveField(model_name="saleorderline", name="product"),
        migrations.RenameField(model_name="saleorderline", old_name="product_variant", new_name="product"),
        migrations.AlterField(
            model_name="saleorderline", name="product",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sale_lines", to="erp_base.productvariant"),
        ),
    ]
