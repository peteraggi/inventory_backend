from django.apps import AppConfig


class ErpBaseConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "inventory_apps.erp_base"
    label = "erp_base"
    verbose_name = "ERP Base"
