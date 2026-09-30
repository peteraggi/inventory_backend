# urls.py - Complete URL Configuration
from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    # Auth views (use your existing ones)
    RegisterView, LoginAPIView, LogoutAPIView,
    RequestPasswordResetEmail, VerifyResetCodeAPIView, SetNewPasswordAPIView,
    VerifyEmailAPIView, ResendVerificationCodeAPIView,
    TeamListView, TeamInviteView, TeamMemberUpdateView, ChangePasswordView,
    MeView,
)

app_name = 'authentication'

urlpatterns = [
    # ============================================
    # AUTHENTICATION ENDPOINTS
    # ============================================
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', LoginAPIView.as_view(), name='login'),
    path('logout/', LogoutAPIView.as_view(), name='logout'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    # Email verification
    path('verify-email/', VerifyEmailAPIView.as_view(), name='verify-email'),
    path('resend-verification-code/', ResendVerificationCodeAPIView.as_view(), name='resend-verification-code'),

    # Password reset
    path('request-reset-email/', RequestPasswordResetEmail.as_view(), name='request-reset-email'),
    path('verify-reset-code/', VerifyResetCodeAPIView.as_view(), name='verify-reset-code'),
    path('password-reset-complete/', SetNewPasswordAPIView.as_view(), name='password-reset-complete'),

    # Self-service password change
    path('change-password/', ChangePasswordView.as_view(), name='change-password'),

    # Self-service profile (name, phone, bio, signature)
    path('me/', MeView.as_view(), name='me'),

    # ============================================
    # STAFF / TEAM MANAGEMENT
    # ============================================
    path('team/', TeamListView.as_view(), name='team-list'),
    path('team/invite/', TeamInviteView.as_view(), name='team-invite'),
    path('team/<uuid:pk>/', TeamMemberUpdateView.as_view(), name='team-update'),
]