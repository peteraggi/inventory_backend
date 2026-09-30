"""Tenant-scoped media storage for the authentication app.

Duplicated from `erp_base.storage.TenantFileSystemStorage` rather than
imported — `authentication` is a SHARED_APP (its models live in the public
schema) and importing from a TENANT_APP would point the dependency the
wrong way. The class itself is tiny and has no model dependencies.
"""
from django.core.files.storage import FileSystemStorage
from django.db import connection


class TenantFileSystemStorage(FileSystemStorage):
    def get_available_name(self, name, max_length=None):
        schema = getattr(connection, "schema_name", "public")
        prefixed = f"{schema}/{name}"
        return super().get_available_name(prefixed, max_length=max_length)
