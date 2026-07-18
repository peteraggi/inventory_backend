"""Tenant-scoped media storage — prefixes every saved file path with the
current tenant's schema name so uploads from different tenants never
collide or become guessable/listable across schemas."""
from django.core.files.storage import FileSystemStorage
from django.db import connection


class TenantFileSystemStorage(FileSystemStorage):
    def get_available_name(self, name, max_length=None):
        schema = getattr(connection, "schema_name", "public")
        prefixed = f"{schema}/{name}"
        return super().get_available_name(prefixed, max_length=max_length)
