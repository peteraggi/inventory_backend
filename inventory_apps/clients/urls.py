from django.urls import path
from .views import (
    OnboardingAPIView,
    ListPlansAPIView,
    WaitlistSignupAPIView,
    WaitlistCountAPIView,
)

app_name = 'clients'

urlpatterns = [
    path('onboard/', OnboardingAPIView.as_view(), name='onboard'),
    path('plans/', ListPlansAPIView.as_view(), name='plans'),
    path('waitlist/', WaitlistSignupAPIView.as_view(), name='waitlist'),
    path('waitlist/count/', WaitlistCountAPIView.as_view(), name='waitlist-count'),
]
