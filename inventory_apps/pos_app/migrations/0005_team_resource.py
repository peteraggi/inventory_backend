"""
Add the team resource to every stored role matrix. Owners manage the team, managers can
invite and edit staff (but not delete them), everyone else has no team access.
"""
from django.db import migrations

TEAM = "team"
GRANTS = {
    "owner": {"read": True, "create": True, "update": True, "delete": True},
    "manager": {"read": True, "create": True, "update": True, "delete": False},
}


def add_team_resource(apps, schema_editor):
    Role = apps.get_model("pos_app", "Role")
    for role in Role.objects.all():
        permissions = role.permissions if isinstance(role.permissions, dict) else {}
        if not permissions:
            continue  # a legacy flat matrix is handled by migration 0003
        grant = GRANTS.get(role.name, {"read": False, "create": False, "update": False, "delete": False})
        permissions[TEAM] = dict(grant)
        role.permissions = permissions
        role.save(update_fields=["permissions"])


class Migration(migrations.Migration):

    dependencies = [
        ("pos_app", "0004_contacts_delete_owner_only"),
    ]

    operations = [
        migrations.RunPython(add_team_resource, migrations.RunPython.noop),
    ]
