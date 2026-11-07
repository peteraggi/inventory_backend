# inventory_apps/notifications/services.py
from typing import Any, Dict, Optional

from django.db.models import QuerySet

from inventory_apps.notifications.models import Notification, NotificationType


class NotificationService:
    """Creates and manages in-app notifications."""

    @staticmethod
    def create_notification(
            user,
            notification_type: str,
            title: str,
            message: str,
            metadata: Optional[Dict[str, Any]] = None,
    ) -> Notification:
        return Notification.objects.create(
            user=user,
            notification_type=notification_type,
            title=title,
            message=message,
            metadata=metadata or {},
        )

    @staticmethod
    def notify_picking_validated(user, picking) -> Notification:
        return NotificationService.create_notification(
            user=user,
            notification_type=NotificationType.PICKING_VALIDATED,
            title="Transfer validated",
            message=f"Transfer {picking.name or picking.id} has been validated and stock updated.",
            metadata={"picking_id": str(picking.id), "picking_name": picking.name},
        )

    @staticmethod
    def notify_picking_cancelled(user, picking) -> Notification:
        return NotificationService.create_notification(
            user=user,
            notification_type=NotificationType.PICKING_CANCELLED,
            title="Transfer cancelled",
            message=f"Transfer {picking.name or picking.id} has been cancelled.",
            metadata={"picking_id": str(picking.id), "picking_name": picking.name},
        )

    @staticmethod
    def notify_adjustment_validated(user, adjustment) -> Notification:
        return NotificationService.create_notification(
            user=user,
            notification_type=NotificationType.ADJUSTMENT_VALIDATED,
            title="Inventory adjustment validated",
            message=f"Adjustment {adjustment.name or adjustment.id} has been validated.",
            metadata={"adjustment_id": str(adjustment.id)},
        )

    @staticmethod
    def get_unread_count(user) -> int:
        return Notification.objects.filter(user=user, is_read=False).count()

    @staticmethod
    def mark_all_as_read(user) -> int:
        from django.utils import timezone
        return Notification.objects.filter(user=user, is_read=False).update(
            is_read=True, read_at=timezone.now(),
        )
