# inventory_apps/notifications/views.py
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from inventory_apps.notifications.models import Notification
from inventory_apps.notifications.serializers import NotificationSerializer
from inventory_apps.notifications.services import NotificationService


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    In-app notifications for the current user.

    list: all notifications (newest first)
    retrieve: one notification
    unread: unread notifications with a count
    unread_count: unread count only
    mark_as_read: mark one notification read
    mark_all_as_read: mark every unread notification read
    """
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)

    @action(detail=False, methods=['get'])
    def unread(self, request):
        queryset = self.get_queryset().filter(is_read=False)
        return Response({
            'count': queryset.count(),
            'results': self.get_serializer(queryset, many=True).data,
        })

    @action(detail=False, methods=['get'])
    def unread_count(self, request):
        return Response({'unread_count': NotificationService.get_unread_count(request.user)})

    @action(detail=True, methods=['post'])
    def mark_as_read(self, request, pk=None):
        notification = self.get_object()
        notification.mark_as_read()
        return Response({
            'message': 'Notification marked as read',
            'notification': self.get_serializer(notification).data,
        })

    @action(detail=False, methods=['post'])
    def mark_all_as_read(self, request):
        count = NotificationService.mark_all_as_read(request.user)
        return Response({'message': f'{count} notifications marked as read', 'count': count})
