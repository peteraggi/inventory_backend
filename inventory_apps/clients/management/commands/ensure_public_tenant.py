"""
Management command: ensure_public_tenant
========================================

django-tenants requires a tenant with schema_name="public" to exist in the
database.  This tenant owns the root domain (e.g. api.logsng.tech) and its
URL conf serves the platform-level API (onboarding, plans, health checks).

Without the public tenant row:
  * TenantMainMiddleware cannot resolve api.logsng.tech to any schema
  * The SHOW_PUBLIC_IF_NO_TENANT_FOUND fallback activates correctly, BUT
    the Caddy tls-ask endpoint will see an empty Domain table and return 403
    for ALL domains including legitimate tenant subdomains, because the public
    tenant domain row that anchors the lookup is missing.

Run this command once after the initial deployment, and again whenever you
restore the database from a backup that did not include the public tenant.
The command is fully idempotent — safe to run multiple times.

Usage
-----
    python manage.py ensure_public_tenant

    # Override the public tenant contact email (must be unique):
    python manage.py ensure_public_tenant --email admin@yourdomain.com

    # Override the canonical root domain (defaults to settings.BASE_DOMAIN):
    python manage.py ensure_public_tenant --domain api.yourdomain.com
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import get_tenant_domain_model, get_tenant_model


class Command(BaseCommand):
    help = (
        "Ensure the django-tenants public tenant and its root domain exist. "
        "Idempotent — safe to run multiple times."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            default="platform@logsng.tech",
            help=(
                "Contact email for the public tenant record. "
                "Must be unique across all tenants. "
                "Default: platform@logsng.tech"
            ),
        )
        parser.add_argument(
            "--domain",
            default=None,
            help=(
                "The canonical root domain to register for the public tenant "
                "(e.g. api.logsng.tech). Defaults to settings.BASE_DOMAIN."
            ),
        )

    def handle(self, *args, **options):
        Tenant = get_tenant_model()
        Domain = get_tenant_domain_model()

        root_domain: str = (options["domain"] or settings.BASE_DOMAIN).lower().strip()
        platform_email: str = options["email"].lower().strip()

        self.stdout.write(self.style.MIGRATE_HEADING("=== ensure_public_tenant ==="))
        self.stdout.write(f"  Root domain  : {root_domain}")
        self.stdout.write(f"  Platform email: {platform_email}")
        self.stdout.write("")

        # ── Step 1: public tenant row ─────────────────────────────────────────
        tenant = self._ensure_public_tenant(Tenant, platform_email)

        # ── Step 2: root domain row ───────────────────────────────────────────
        self._ensure_root_domain(Domain, tenant, root_domain)

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS("Public tenant setup is complete.")
        )
        self.stdout.write(
            "Run the tls-ask probe to verify:\n"
            f"  docker exec inventory_caddy_container wget -qO- "
            f"'http://tls_ask_service:8000/internal/tls-ask/?domain=<subdomain>.{root_domain}'"
        )

    # ── helpers ───────────────────────────────────────────────────────────────

    def _ensure_public_tenant(self, Tenant, platform_email: str):
        """Get or create the public-schema tenant row."""
        try:
            tenant = Tenant.objects.get(schema_name="public")
            self.stdout.write(
                self.style.SUCCESS("  [OK] Public tenant already exists")
                + f"  (pk={tenant.pk}, name={tenant.name!r})"
            )
            return tenant
        except Tenant.DoesNotExist:
            pass

        self.stdout.write("  [..] Creating public tenant …")

        # Guard: contact_email must be unique — check before writing.
        if Tenant.objects.filter(contact_email=platform_email).exists():
            raise CommandError(
                f"A tenant with contact_email={platform_email!r} already exists "
                "but it is NOT the public tenant.  "
                "Pass a different --email, e.g.:\n"
                "  python manage.py ensure_public_tenant --email ops@yourplatform.com"
            )

        tenant = Tenant(
            schema_name="public",
            name="LogsInventory Platform",
            contact_name="Platform Admin",
            contact_email=platform_email,
            on_trial=False,
        )
        # auto_create_schema=True on the model calls CREATE SCHEMA IF NOT EXISTS
        # and runs pending migrations for the public schema.  This is idempotent
        # because the public schema always exists in PostgreSQL.
        tenant.save()

        self.stdout.write(
            self.style.SUCCESS(f"  [OK] Public tenant created  (pk={tenant.pk})")
        )
        return tenant

    def _ensure_root_domain(self, Domain, tenant, root_domain: str):
        """Get or create the Domain row that maps root_domain to the public tenant."""
        try:
            existing = Domain.objects.get(domain=root_domain)
            if existing.tenant_id != tenant.pk:
                raise CommandError(
                    f"Domain {root_domain!r} exists but belongs to tenant "
                    f"{existing.tenant!r} (schema={existing.tenant.schema_name!r}), "
                    "not the public tenant.  Resolve this conflict manually."
                )
            self.stdout.write(
                self.style.SUCCESS(f"  [OK] Domain {root_domain!r} already registered")
                + " to the public tenant."
            )
            return existing
        except Domain.DoesNotExist:
            pass

        self.stdout.write(f"  [..] Registering domain {root_domain!r} …")
        domain_obj = Domain.objects.create(
            domain=root_domain,
            tenant=tenant,
            is_primary=True,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"  [OK] Domain {root_domain!r} registered  (pk={domain_obj.pk})"
            )
        )
        return domain_obj
