"""
Only owners may delete customers and vendors. Existing non-owner roles lose the
contacts.delete grant they were seeded with; owners keep theirs.
"""
from django.db import migrations


def remove_contact_delete_for_non_owners(apps, schema_editor):
    Role = apps.get_model("pos_app", "Role")
    for role in Role.objects.exclude(name="owner"):
        permissions = role.permissions if isinstance(role.permissions, dict) else {}
        contacts = permissions.get("contacts")
        if isinstance(contacts, dict) and contacts.get("delete"):
            contacts["delete"] = False
            role.permissions = permissions
            role.save(update_fields=["permissions"])


class Migration(migrations.Migration):

    dependencies = [
        ("pos_app", "0003_sync_role_permissions"),
    ]

    operations = [
        migrations.RunPython(remove_contact_delete_for_non_owners, migrations.RunPython.noop),
    ]
