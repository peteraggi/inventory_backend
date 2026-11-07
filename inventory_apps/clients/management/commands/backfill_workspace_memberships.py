"""
Link existing users to the businesses they work in.

Run once after deploying the workspace migration, for the whole platform:

    python manage.py backfill_workspace_memberships

A user is linked to every business whose schema contains their store. Users who are
already linked are updated, not duplicated, so the command is safe to re-run.
"""
from django.core.management.base import BaseCommand
from django_tenants.utils import get_public_schema_name, schema_context

from inventory_apps.authentication.models import User
from inventory_apps.clients.models import Client
from inventory_apps.clients.workspaces import link_user


class Command(BaseCommand):
    help = "Create workspace memberships for existing users, business by business."

    def handle(self, *args, **options):
        linked = 0
        for client in Client.objects.exclude(schema_name=get_public_schema_name()):
            with schema_context(client.schema_name):
                from inventory_apps.pos_app.models import Store
                store_ids = list(Store.objects.values_list("id", flat=True))
            for user in User.objects.filter(store_id__in=store_ids):
                link_user(
                    user,
                    store_id=user.store_id,
                    role_id=user.role_id,
                    client=client,
                    permission_overrides=user.permission_overrides or {},
                )
                linked += 1
        self.stdout.write(self.style.SUCCESS(f"Workspace memberships linked: {linked}"))
