# inventory_apps/notifications/serializers.py
from rest_framework import serializers

from inventory_apps.notifications.models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = [
            'id', 'notification_type', 'title', 'message',
            'metadata', 'is_read', 'read_at', 'created_at',
        ]
        read_only_fields = fields
