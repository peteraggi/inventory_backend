from django.apps import AppConfig


class ErpAccountingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "inventory_apps.erp_accounting"
    label = "erp_accounting"
    verbose_name = "ERP Accounting"
