# inventory_apps/erp_inventory/test_concurrency.py
"""
Two validations racing on the same stock must not lose an update.

Threads need to see committed data and use their own database connections, so this
is a TransactionTestCase with its own tenant schema rather than a TenantTestCase.
"""
import threading
from decimal import Decimal

from django.db import connection
from django.test import TransactionTestCase

from inventory_apps.clients.models import Client, Domain
from inventory_apps.erp_base.models import ProductTemplate
from inventory_apps.erp_inventory.models import (
    InventoryCostLayer, StockLedgerEntry, StockMove, StockPicking, StockQuant, Warehouse,
)
from inventory_apps.erp_inventory.services import StockService

SCHEMA = "concurrency_test"


class ConcurrentValidationTests(TransactionTestCase):

    def setUp(self):
        self.tenant = Client.objects.create(
            schema_name=SCHEMA, name="Concurrency Test", contact_name="Tester",
            contact_email="concurrency@test.local",
        )
        Domain.objects.create(tenant=self.tenant, domain="concurrency.test.local", is_primary=True)
        connection.set_tenant(self.tenant)

        warehouse = Warehouse.objects.create(name="Race", short_name="RC")
        self.stock = warehouse.lot_stock_location
        self.vendor = warehouse.picking_types.get(code="incoming").default_location_src
        self.customer = warehouse.picking_types.get(code="outgoing").default_location_dest
        self.product = ProductTemplate.objects.create(name="Racer", internal_reference="RC-1").variants.first()

        receipt = self.make_picking(
            warehouse.picking_types.get(code="incoming"), self.vendor, self.stock, qty=20, price=5,
        )
        StockService.validate_picking(receipt)

    def tearDown(self):
        connection.set_schema_to_public()
        self.tenant.delete(force_drop=True)

    def make_picking(self, picking_type, src, dest, qty, price=None):
        picking = StockPicking.objects.create(
            picking_type=picking_type, location_src=src, location_dest=dest, state="confirmed",
        )
        StockMove.objects.create(
            picking=picking, product=self.product, product_uom_qty=Decimal(qty),
            price_unit=Decimal(price or 0), location_src=src, location_dest=dest, state="confirmed",
        )
        return picking

    def test_two_simultaneous_deliveries_both_apply(self):
        delivery_type = Warehouse.objects.get().picking_types.get(code="outgoing")
        picking_ids = [
            self.make_picking(delivery_type, self.stock, self.customer, qty=8).id,
            self.make_picking(delivery_type, self.stock, self.customer, qty=8).id,
        ]

        barrier = threading.Barrier(len(picking_ids))
        errors = []

        def validate(picking_id):
            try:
                connection.set_tenant(self.tenant)
                picking = StockPicking.objects.get(pk=picking_id)
                barrier.wait()
                StockService.validate_picking(picking)
            except Exception as exc:  # reported after the threads finish
                errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=validate, args=(pid,)) for pid in picking_ids]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        connection.set_tenant(self.tenant)

        # 20 received, 16 delivered: 4 left. A lost update would leave the quant at 12.
        quant = StockQuant.objects.get(product=self.product, location=self.stock)
        self.assertEqual(quant.quantity, Decimal("4"))

        # Every delivery is recorded once on the stock side.
        stock_side = StockLedgerEntry.objects.filter(location=self.stock, change_type="DELIVERY")
        self.assertEqual(stock_side.count(), 2)
        self.assertEqual(sum(e.quantity_change for e in stock_side), Decimal("-16"))

        # The receipt's layer keeps the 4 units nobody took.
        self.assertEqual(
            sum((layer.quantity_remaining for layer in InventoryCostLayer.objects.filter(location=self.stock)),
                Decimal("0")),
            Decimal("4"),
        )
        self.assertEqual(
            StockPicking.objects.filter(pk__in=picking_ids, state="done").count(), 2,
        )
