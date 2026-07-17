"""
Management command: python manage.py erp_setup
Run once per tenant (or via migrate_schemas post-migrate signal) to seed default
ERP master data: currency, company, chart of accounts, journals, UOMs, warehouse.
"""
from django.core.management.base import BaseCommand
from django_tenants.utils import schema_context


class Command(BaseCommand):
    help = "Seed default ERP data for all tenants (or a specific schema)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--schema",
            type=str,
            default=None,
            help="Run only for this tenant schema",
        )

    def handle(self, *args, **options):
        from django_tenants.utils import get_tenant_model
        from inventory_apps.erp_base.services import SetupService

        TenantModel = get_tenant_model()
        schemas = TenantModel.objects.exclude(schema_name="public")
        if options["schema"]:
            schemas = schemas.filter(schema_name=options["schema"])

        for tenant in schemas:
            self.stdout.write(f"Seeding ERP data for schema: {tenant.schema_name}")
            with schema_context(tenant.schema_name):
                try:
                    result = SetupService.seed_default_data()
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  ✓ {tenant.schema_name}: company={result['company']}, "
                            f"currency={result['currency']}, warehouse={result['warehouse']}"
                        )
                    )
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f"  ✗ {tenant.schema_name}: {e}")
                    )
