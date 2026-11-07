"""
Replace legacy flat role permissions with the resource/action matrix.

Tenants created before the matrix existed were seeded with keys such as
"manage_users": True, which the permission check cannot read, so their owner,
managers and salespeople were locked out of every module. Roles already in the
matrix format are left untouched, so customised permissions are preserved.
"""
from django.db import migrations

from inventory_apps.erp_base.rbac_constants import DEFAULT_ROLE_PERMISSIONS, RESOURCES


def _is_matrix(permissions):
    return isinstance(permissions, dict) and all(
        key in RESOURCES.values() and isinstance(value, dict)
        for key, value in permissions.items()
    )


def sync_role_permissions(apps, schema_editor):
    Role = apps.get_model("pos_app", "Role")
    for role in Role.objects.all():
        if _is_matrix(role.permissions) and role.permissions:
            continue
        role.permissions = DEFAULT_ROLE_PERMISSIONS.get(role.name, {})
        role.save(update_fields=["permissions"])


class Migration(migrations.Migration):

    dependencies = [
        ("pos_app", "0002_alter_store_options_category_cost_method_and_more"),
    ]

    operations = [
        migrations.RunPython(sync_role_permissions, migrations.RunPython.noop),
    ]
