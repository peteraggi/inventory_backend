"""
Give stock that predates the ledger an OPENING_BALANCE entry and a cost layer.

Run once per tenant schema, after deploying the ledger migration:

    python manage.py tenant_command backfill_inventory_layers --schema=<tenant> --dry-run
    python manage.py tenant_command backfill_inventory_layers --schema=<tenant>

Stock is valued at the product's standard cost. Locations that already have
layers, or an opening entry, are skipped, so the command is safe to re-run.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from inventory_apps.erp_inventory.models import (
    InventoryCostLayer, StockLedgerEntry, StockQuant,
)
from inventory_apps.erp_inventory.valuation import standard_cost


class Command(BaseCommand):
    help = "Create opening ledger entries and cost layers for existing internal stock."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would be created without writing anything.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        created = 0
        quants = StockQuant.objects.filter(
            location__usage="internal", quantity__gt=0,
        ).select_related("product__product_template", "location", "lot")

        for quant in quants:
            already_layered = InventoryCostLayer.objects.filter(
                product=quant.product, location=quant.location, lot=quant.lot,
            ).exists()
            already_opened = StockLedgerEntry.objects.filter(
                product=quant.product, location=quant.location, lot=quant.lot,
                change_type="OPENING_BALANCE",
            ).exists()
            if already_layered or already_opened:
                continue

            if dry_run:
                created += 1
                continue

            with transaction.atomic():
                cost = standard_cost(quant.product)
                InventoryCostLayer.objects.create(
                    product=quant.product,
                    location=quant.location,
                    lot=quant.lot,
                    quantity_received=quant.quantity,
                    quantity_remaining=quant.quantity,
                    unit_cost=cost,
                    source_reference="OPENING",
                )
                StockLedgerEntry.objects.create(
                    product=quant.product,
                    location=quant.location,
                    lot=quant.lot,
                    change_type="OPENING_BALANCE",
                    quantity_change=quant.quantity,
                    resulting_quantity=quant.quantity,
                    unit_cost=cost,
                    reference_type="OPENING",
                    reference_name="Opening balance",
                )
            created += 1

        label = "Would create opening balances" if dry_run else "Opening balances created"
        self.stdout.write(self.style.SUCCESS(f"{label}: {created}"))
