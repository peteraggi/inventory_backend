from django.apps import AppConfig


class ErpPurchaseConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "inventory_apps.erp_purchase"
    label = "erp_purchase"
    verbose_name = "ERP Purchase"
