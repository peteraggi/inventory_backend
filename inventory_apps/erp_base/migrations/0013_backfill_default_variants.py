from django.db import migrations


def backfill_default_variants(apps, schema_editor):
    ProductTemplate = apps.get_model("erp_base", "ProductTemplate")
    ProductVariant = apps.get_model("erp_base", "ProductVariant")
    for template in ProductTemplate.objects.all():
        if not template.variants.filter(active=True).exists():
            default = template.variants.filter(attribute_values__isnull=True).first()
            if default:
                if not default.active:
                    default.active = True
                    default.save(update_fields=["active"])
            else:
                ProductVariant.objects.create(product_template=template)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("erp_base", "0012_productattribute_productattributevalue_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_default_variants, noop_reverse),
    ]
