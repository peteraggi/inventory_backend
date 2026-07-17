from django.apps import AppConfig


class ErpInventoryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "inventory_apps.erp_inventory"
    label = "erp_inventory"
    verbose_name = "ERP Inventory"
