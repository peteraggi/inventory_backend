import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Drop the DB-level FK constraints on authentication_user.role_id and
    authentication_user.store_id.

    Both Role and Store live in the per-tenant PostgreSQL schema, while
    authentication_user lives in the shared (public) schema.  PostgreSQL
    cannot enforce referential integrity across schemas, so keeping these
    constraints causes a FK violation on every tenant onboarding call.
    db_constraint=False preserves the Django ORM relationship (queries,
    select_related, etc.) while removing the cross-schema constraint.
    """

    dependencies = [
        ("authentication", "0002_alter_user_options_user_role_user_store_and_more"),
        ("pos_app", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                help_text="User's role in the system",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="users",
                to="pos_app.role",
            ),
        ),
        migrations.AlterField(
            model_name="user",
            name="store",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                help_text="Store the user belongs to",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="users",
                to="pos_app.store",
            ),
        ),
    ]
