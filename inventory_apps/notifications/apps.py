from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "inventory_apps.notifications"
    label = "notifications"
    verbose_name = "In-App Notifications"
