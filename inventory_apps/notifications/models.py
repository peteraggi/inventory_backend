# inventory_apps/notifications/models.py
import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone


class NotificationType(models.TextChoices):
    """In-app notification types raised by inventory operations"""
    PICKING_VALIDATED = 'PICKING_VALIDATED', 'Transfer Validated'
    PICKING_CANCELLED = 'PICKING_CANCELLED', 'Transfer Cancelled'
    ADJUSTMENT_VALIDATED = 'ADJUSTMENT_VALIDATED', 'Inventory Adjustment Validated'
    STOCK_COUNT_APPLIED = 'STOCK_COUNT_APPLIED', 'Physical Count Applied'
    SCRAP_VALIDATED = 'SCRAP_VALIDATED', 'Scrap Order Validated'
    REPLENISHMENT_CREATED = 'REPLENISHMENT_CREATED', 'Replenishment Receipts Created'
    GENERAL = 'GENERAL', 'General'


class Notification(models.Model):
    """In-app message for a single user."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
    )

    notification_type = models.CharField(
        max_length=50,
        choices=NotificationType.choices,
        default=NotificationType.GENERAL,
    )
    title = models.CharField(max_length=255)
    message = models.TextField()

    # Free-form pointer to the record this message is about (e.g. {"picking_id": "..."})
    metadata = models.JSONField(default=dict, blank=True)

    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['user', 'is_read']),
        ]

    def __str__(self):
        return f"{self.notification_type} - {self.user_id}"

    def mark_as_read(self):
        """Mark notification as read (no-op if already read)."""
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at', 'updated_at'])
