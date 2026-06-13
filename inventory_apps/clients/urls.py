from django.urls import path
from .views import OnboardingAPIView, ListPlansAPIView

app_name = 'clients'

urlpatterns = [
    path('onboard/', OnboardingAPIView.as_view(), name='onboard'),
    path('plans/', ListPlansAPIView.as_view(), name='plans'),
]
