from django.db import migrations


def _resolve_variant_id(template_id, cache, ProductVariant):
    if template_id in cache:
        return cache[template_id]
    variant = (
        ProductVariant.objects.filter(product_template_id=template_id, attribute_values__isnull=True).first()
        or ProductVariant.objects.filter(product_template_id=template_id).order_by("created_at").first()
    )
    if variant is None:
        variant = ProductVariant.objects.create(product_template_id=template_id)
    cache[template_id] = variant.id
    return variant.id


def backfill(apps, schema_editor):
    ProductVariant = apps.get_model("erp_base", "ProductVariant")
    StockLot = apps.get_model("erp_inventory", "StockLot")
    StockMove = apps.get_model("erp_inventory", "StockMove")
    StockQuant = apps.get_model("erp_inventory", "StockQuant")
    StockInventoryAdjustmentLine = apps.get_model("erp_inventory", "StockInventoryAdjustmentLine")
    ReorderingRule = apps.get_model("erp_inventory", "ReorderingRule")

    cache = {}
    for Model in (StockLot, StockMove, StockQuant, StockInventoryAdjustmentLine, ReorderingRule):
        for row in Model.objects.all():
            row.product_variant_id = _resolve_variant_id(row.product_id, cache, ProductVariant)
            row.save(update_fields=["product_variant"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("erp_inventory", "0003_add_variant_fk_fields"),
    ]

    operations = [
        migrations.RunPython(backfill, noop_reverse),
    ]
