# inventory_apps/notifications/urls.py
from django.urls import path, include
from rest_framework.routers import SimpleRouter

from inventory_apps.notifications.views import NotificationViewSet

# SimpleRouter, not DefaultRouter: an empty prefix would let the API-root view shadow the list.
router = SimpleRouter()
router.register(r'', NotificationViewSet, basename='notification')

app_name = 'notifications'

urlpatterns = [
    path('', include(router.urls)),
]

# Mounted under /notifications/:
"""
GET   /notifications/                      - List notifications
GET   /notifications/{id}/                 - Notification detail
GET   /notifications/unread/               - Unread notifications + count
GET   /notifications/unread_count/         - Unread count
POST  /notifications/{id}/mark_as_read/    - Mark one read
POST  /notifications/mark_all_as_read/     - Mark all read
"""
