from django.apps import AppConfig


class ErpPosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "inventory_apps.erp_pos"
    label = "erp_pos"
    verbose_name = "ERP Point of Sale"
