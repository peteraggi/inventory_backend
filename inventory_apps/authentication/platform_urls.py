# inventory_apps/authentication/platform_urls.py
from django.urls import path

from inventory_apps.authentication.platform import PlatformLoginView, PlatformSelectWorkspaceView, PlatformSwitchView
from inventory_apps.authentication.views import (
    RequestPasswordResetEmail, SetNewPasswordAPIView, VerifyResetCodeAPIView,
)

app_name = "platform_auth"

urlpatterns = [
    path("login/", PlatformLoginView.as_view(), name="login"),
    path("select-workspace/", PlatformSelectWorkspaceView.as_view(), name="select-workspace"),
    path("switch/", PlatformSwitchView.as_view(), name="switch"),
    # Password reset works by email across every business, so it lives on the root domain too.
    path("password-reset/email/", RequestPasswordResetEmail.as_view(), name="reset-email"),
    path("password-reset/verify/", VerifyResetCodeAPIView.as_view(), name="reset-verify"),
    path("password-reset/complete/", SetNewPasswordAPIView.as_view(), name="reset-complete"),
]
