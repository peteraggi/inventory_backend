# inventory_apps/clients/onboarding.py
"""
Helpers for registering a business. Checks run before anything is created, and a registration
that fails part-way is cleaned up, so the same details can be tried again.
"""
import logging
import re

from django.db import connection

logger = logging.getLogger(__name__)


def schema_name_for(subdomain):
    """The PostgreSQL schema for a subdomain, e.g. 'acme-retail' becomes 'acme_retail'."""
    return re.sub(r"[^a-z0-9]", "_", subdomain.lower())


def schema_exists(schema_name):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name = %s", [schema_name])
        return cursor.fetchone() is not None


def discard_partial_setup(client, schema_name, email):
    """
    Remove what a failed registration left behind: the business schema, its client row and the
    owner's account. Only called for names the registration checked were free before it started.
    """
    from inventory_apps.authentication.models import User

    if client is not None and client.pk:
        try:
            client.delete(force_drop=True)
        except Exception:
            logger.exception("Could not remove the client row for failed onboarding %s", schema_name)
    if schema_exists(schema_name):
        try:
            with connection.cursor() as cursor:
                cursor.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
        except Exception:
            logger.exception("Could not drop schema %s after failed onboarding", schema_name)
    try:
        User.objects.filter(email=email).delete()
    except Exception:
        logger.exception("Could not remove the owner account for failed onboarding %s", email)
