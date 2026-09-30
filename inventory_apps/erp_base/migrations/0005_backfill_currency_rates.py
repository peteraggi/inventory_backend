from django.db import migrations
from django.utils import timezone


def backfill_currency_rates(apps, schema_editor):
    Currency = apps.get_model("erp_base", "Currency")
    CurrencyRate = apps.get_model("erp_base", "CurrencyRate")
    today = timezone.now().date()
    for currency in Currency.objects.all():
        if not CurrencyRate.objects.filter(currency=currency).exists():
            CurrencyRate.objects.create(currency=currency, rate=currency.rate, rate_date=today)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("erp_base", "0004_currencyrate"),
    ]

    operations = [
        migrations.RunPython(backfill_currency_rates, noop_reverse),
    ]
