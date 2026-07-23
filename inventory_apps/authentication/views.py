from django.core.cache import cache
from rest_framework import generics, status, views, permissions
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_str, force_bytes
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from .utils import Util
from .models import User
from .renderers import UserRenderer
from .permissions import IsOwnerOrManager
from .serializers import (
    RegisterSerializer, SetNewPasswordSerializer,
    ResetPasswordEmailRequestSerializer, EmailVerificationSerializer,
    LoginSerializer, LogoutSerializer, VerifyResetCodeSerializer,
    ResendVerificationCodeSerializer, TeamMemberSerializer,
    TeamMemberInviteSerializer, TeamMemberUpdateSerializer,
    ChangePasswordSerializer,
)
from ..pos_app.permissions import IsOwner
import random
import string
import logging

logger = logging.getLogger(__name__)

# ─── Reusable response schemas ────────────────────────────────────────────────

_TOKEN_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    properties={
        'access':  openapi.Schema(type=openapi.TYPE_STRING, description='Short-lived JWT access token (10 min)'),
        'refresh': openapi.Schema(type=openapi.TYPE_STRING, description='Long-lived JWT refresh token (30 days)'),
    },
)

_ERROR_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    properties={'error': openapi.Schema(type=openapi.TYPE_STRING)},
)


def generate_token_code():
    """Generate a 6-digit numeric verification code."""
    return ''.join(random.choices(string.digits, k=6))


class RegisterView(generics.GenericAPIView):
    serializer_class = RegisterSerializer
    renderer_classes = (UserRenderer,)

    @swagger_auto_schema(
        tags=['Authentication'],
        operation_summary='Register a new user',
        operation_description=(
            'Creates a new user account within the current tenant schema. '
            'The caller must supply a valid **store_id** and **role_id** from this tenant. '
            'On success a 6-digit verification code is emailed to the user.'
        ),
        request_body=RegisterSerializer,
        responses={
            201: openapi.Response(
                description='User created — verification email sent',
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'email':                  openapi.Schema(type=openapi.TYPE_STRING),
                        'user_id':                openapi.Schema(type=openapi.TYPE_STRING, format='uuid'),
                        'username':               openapi.Schema(type=openapi.TYPE_STRING),
                        'store_name':             openapi.Schema(type=openapi.TYPE_STRING),
                        'role_name':              openapi.Schema(type=openapi.TYPE_STRING),
                        'message':                openapi.Schema(type=openapi.TYPE_STRING),
                        'verification_required':  openapi.Schema(type=openapi.TYPE_BOOLEAN),
                        'code_expires_in':        openapi.Schema(type=openapi.TYPE_STRING),
                    },
                ),
            ),
            400: openapi.Response('Validation error', schema=_ERROR_SCHEMA),
            500: openapi.Response('Email send failed', schema=_ERROR_SCHEMA),
        },
    )
    def post(self, request):
        try:
            serializer = self.serializer_class(data=request.data)
            serializer.is_valid(raise_exception=True)
            serializer.save()

            user_response_data = serializer.data
            user = User.objects.get(email=user_response_data['email'])

            verification_code = generate_token_code()
            cache_key = f'email_verification_{user.pk}'
            cache.set(cache_key, {
                'code': verification_code,
                'user_id': user.pk,
                'attempts': 0,
                'email': user.email,
            }, timeout=1800)

            email_body = (
                f'Hello {user.name},\n\n'
                'Welcome to our platform! To complete your registration, '
                'please verify your email address.\n\n'
                f'Your email verification code is: {verification_code}\n\n'
                'This code will expire in 30 minutes.\n\n'
                'Best regards,\nAEACBIO TEAM'
            )
            email_sent = Util.send_email({
                'email_body': email_body,
                'to_email': user.email,
                'email_subject': 'Verify Your Email Address',
            })

            if not email_sent:
                logger.warning(f'Failed to send verification email to {user.email}')
                cache.delete(cache_key)
                return Response(
                    {'error': 'Failed to send verification code. Please try again.'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            response_data = dict(user_response_data)
            response_data.update({
                'message': 'Registration successful. Please check your email for the verification code.',
                'verification_required': True,
                'code_expires_in': '30 minutes',
            })
            return Response(response_data, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f'Error in user registration: {e}', exc_info=True)
            return Response(
                {'error': f'Registration failed: {e}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class VerifyEmailAPIView(views.APIView):
    serializer_class = EmailVerificationSerializer

    @swagger_auto_schema(
        tags=['Authentication'],
        operation_summary='Verify email address',
        operation_description=(
            'Submit the 6-digit code that was emailed after registration. '
            'On success the account is marked verified and JWT tokens are returned.'
        ),
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['email', 'code'],
            properties={
                'email': openapi.Schema(type=openapi.TYPE_STRING, format='email'),
                'code':  openapi.Schema(type=openapi.TYPE_STRING, description='6-digit code from email', example='123456'),
            },
        ),
        responses={
            200: openapi.Response(
                description='Email verified — tokens issued',
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'success':  openapi.Schema(type=openapi.TYPE_BOOLEAN),
                        'message':  openapi.Schema(type=openapi.TYPE_STRING),
                        'user_id':  openapi.Schema(type=openapi.TYPE_STRING, format='uuid'),
                        'email':    openapi.Schema(type=openapi.TYPE_STRING),
                        'username': openapi.Schema(type=openapi.TYPE_STRING),
                        'tokens':   _TOKEN_SCHEMA,
                    },
                ),
            ),
            400: openapi.Response('Invalid or expired code', schema=_ERROR_SCHEMA),
        },
    )
    def post(self, request):
        try:
            serializer = self.serializer_class(data=request.data)
            serializer.is_valid(raise_exception=True)

            email = request.data.get('email')
            code = request.data.get('code')

            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                return Response({'error': 'Invalid email or verification code'}, status=status.HTTP_400_BAD_REQUEST)

            if user.is_verified:
                return Response({
                    'success': True,
                    'message': 'Email is already verified',
                    'user_id': str(user.id),
                    'email': user.email,
                }, status=status.HTTP_200_OK)

            cache_key = f'email_verification_{user.pk}'
            cached_data = cache.get(cache_key)

            if not cached_data:
                return Response(
                    {'error': 'Verification code has expired. Please request a new one.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if cached_data['attempts'] >= 5:
                cache.delete(cache_key)
                return Response(
                    {'error': 'Too many failed attempts. Please request a new verification code.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if cached_data['code'] != code:
                cached_data['attempts'] += 1
                cache.set(cache_key, cached_data, timeout=1800)
                return Response({
                    'error': 'Invalid verification code',
                    'attempts_remaining': 5 - cached_data['attempts'],
                }, status=status.HTTP_400_BAD_REQUEST)

            user.is_verified = True
            user.save()
            cache.delete(cache_key)

            refresh = RefreshToken.for_user(user)
            return Response({
                'success': True,
                'message': 'Email verified successfully',
                'user_id': str(user.id),
                'email': user.email,
                'username': user.username,
                'tokens': {
                    'refresh': str(refresh),
                    'access': str(refresh.access_token),
                },
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f'Error in email verification: {e}')
            return Response(
                {'error': 'Email verification failed. Please try again.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ResendVerificationCodeAPIView(views.APIView):
    serializer_class = ResendVerificationCodeSerializer

    @swagger_auto_schema(
        tags=['Authentication'],
        operation_summary='Resend email verification code',
        operation_description='Issues a new 6-digit code and emails it. Previous code is invalidated.',
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['email'],
            properties={'email': openapi.Schema(type=openapi.TYPE_STRING, format='email')},
        ),
        responses={
            200: openapi.Response('New code sent', schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    'success':         openapi.Schema(type=openapi.TYPE_STRING),
                    'message':         openapi.Schema(type=openapi.TYPE_STRING),
                    'code_expires_in': openapi.Schema(type=openapi.TYPE_STRING),
                },
            )),
            404: openapi.Response('Email not found', schema=_ERROR_SCHEMA),
            500: openapi.Response('Email send failed', schema=_ERROR_SCHEMA),
        },
    )
    def post(self, request):
        try:
            serializer = self.serializer_class(data=request.data)
            serializer.is_valid(raise_exception=True)

            email = request.data.get('email')
            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                return Response(
                    {'error': 'No account found with this email address'},
                    status=status.HTTP_404_NOT_FOUND,
                )

            if user.is_verified:
                return Response({'message': 'Email is already verified'}, status=status.HTTP_200_OK)

            verification_code = generate_token_code()
            cache_key = f'email_verification_{user.pk}'
            cache.set(cache_key, {
                'code': verification_code,
                'user_id': user.pk,
                'attempts': 0,
                'email': user.email,
            }, timeout=1800)

            email_body = (
                f'Hello {user.username},\n\n'
                f'Your new email verification code is: {verification_code}\n\n'
                'This code will expire in 30 minutes.\n\n'
                'Best regards,\nAEACBIO TEAM'
            )
            email_sent = Util.send_email({
                'email_body': email_body,
                'to_email': user.email,
                'email_subject': 'New Email Verification Code',
            })

            if not email_sent:
                logger.warning(f'Failed to resend verification email to {user.email}')
                cache.delete(cache_key)
                return Response(
                    {'error': 'Failed to send verification code. Please try again.'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            return Response({
                'success': 'New verification code sent to your email',
                'message': 'Please check your email for the new 6-digit verification code',
                'code_expires_in': '30 minutes',
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f'Error resending verification code: {e}')
            return Response(
                {'error': 'Failed to resend verification code. Please try again.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class LoginAPIView(generics.GenericAPIView):
    serializer_class = LoginSerializer

    @swagger_auto_schema(
        tags=['Authentication'],
        operation_summary='Login',
        operation_description=(
            'Authenticate with email and password. '
            'Returns user profile and JWT tokens. '
            'The account must be email-verified before login is allowed.'
        ),
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['email', 'password'],
            properties={
                'email':    openapi.Schema(type=openapi.TYPE_STRING, format='email'),
                'password': openapi.Schema(type=openapi.TYPE_STRING, format='password'),
            },
        ),
        responses={
            200: openapi.Response(
                description='Login successful',
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'email':      openapi.Schema(type=openapi.TYPE_STRING),
                        'name':       openapi.Schema(type=openapi.TYPE_STRING),
                        'username':   openapi.Schema(type=openapi.TYPE_STRING),
                        'user_id':    openapi.Schema(type=openapi.TYPE_STRING, format='uuid'),
                        'store_id':   openapi.Schema(type=openapi.TYPE_STRING, format='uuid'),
                        'store_name': openapi.Schema(type=openapi.TYPE_STRING),
                        'role':       openapi.Schema(type=openapi.TYPE_STRING, example='owner'),
                        'tokens':     _TOKEN_SCHEMA,
                    },
                ),
            ),
            401: openapi.Response('Invalid credentials / unverified account', schema=_ERROR_SCHEMA),
        },
    )
    def post(self, request):
        serializer = self.serializer_class(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        logger.debug(f'Login response data: {serializer.data}')
        return Response(serializer.data, status=status.HTTP_200_OK)


class RequestPasswordResetEmail(generics.GenericAPIView):
    serializer_class = ResetPasswordEmailRequestSerializer

    @swagger_auto_schema(
        tags=['Authentication'],
        operation_summary='Request password reset code',
        operation_description=(
            'Sends a 6-digit reset code to the given email if an account exists. '
            'Always returns 200 to prevent email enumeration.'
        ),
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['email'],
            properties={'email': openapi.Schema(type=openapi.TYPE_STRING, format='email')},
        ),
        responses={
            200: openapi.Response('Reset code sent (or silently skipped)', schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    'success':         openapi.Schema(type=openapi.TYPE_STRING),
                    'message':         openapi.Schema(type=openapi.TYPE_STRING),
                    'code_expires_in': openapi.Schema(type=openapi.TYPE_STRING),
                },
            )),
        },
    )
    def post(self, request):
        try:
            serializer = self.serializer_class(data=request.data)
            serializer.is_valid(raise_exception=True)

            email = request.data.get('email', '')
            if User.objects.filter(email=email).exists():
                user = User.objects.get(email=email)
                reset_code = generate_token_code()
                cache_key = f'password_reset_{user.pk}'
                cache.set(cache_key, {
                    'code': reset_code,
                    'user_id': user.pk,
                    'attempts': 0,
                }, timeout=900)

                email_body = (
                    f'Hello {user.username},\n\n'
                    'You requested a password reset.\n\n'
                    f'Your reset code is: {reset_code}\n\n'
                    'This code expires in 15 minutes. '
                    'If you did not request this, ignore this email.\n\n'
                    'Best regards,\nAEACBIO TEAM'
                )
                email_sent = Util.send_email({
                    'email_body': email_body,
                    'to_email': user.email,
                    'email_subject': 'Your Password Reset Code',
                })
                if not email_sent:
                    logger.warning(f'Failed to send reset email to {user.email}')
                    cache.delete(cache_key)
                    return Response(
                        {'error': 'Failed to send reset code. Please try again.'},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )

            return Response({
                'success': 'If an account with this email exists, we have sent you a password reset code.',
                'message': 'Please check your email for the 6-digit reset code.',
                'code_expires_in': '15 minutes',
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f'Error in password reset request: {e}')
            return Response(
                {'error': 'Password reset request failed. Please try again.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class VerifyResetCodeAPIView(generics.GenericAPIView):
    serializer_class = VerifyResetCodeSerializer

    @swagger_auto_schema(
        tags=['Authentication'],
        operation_summary='Verify password reset code',
        operation_description=(
            'Validates the 6-digit code from the reset email. '
            'On success returns a short-lived **reset_token** and **uidb64** '
            'required for the final password-reset step. '
            'Max 3 attempts; the code is invalidated after that.'
        ),
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['email', 'code'],
            properties={
                'email': openapi.Schema(type=openapi.TYPE_STRING, format='email'),
                'code':  openapi.Schema(type=openapi.TYPE_STRING, description='6-digit code', example='654321'),
            },
        ),
        responses={
            200: openapi.Response(
                description='Code verified',
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'success':     openapi.Schema(type=openapi.TYPE_BOOLEAN),
                        'message':     openapi.Schema(type=openapi.TYPE_STRING),
                        'reset_token': openapi.Schema(type=openapi.TYPE_STRING),
                        'uidb64':      openapi.Schema(type=openapi.TYPE_STRING),
                        'expires_in':  openapi.Schema(type=openapi.TYPE_STRING),
                    },
                ),
            ),
            400: openapi.Response('Invalid or expired code', schema=_ERROR_SCHEMA),
        },
    )
    def post(self, request):
        try:
            serializer = self.serializer_class(data=request.data)
            serializer.is_valid(raise_exception=True)

            email = request.data.get('email')
            code = request.data.get('code')

            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                return Response({'error': 'Invalid email or code'}, status=status.HTTP_400_BAD_REQUEST)

            cache_key = f'password_reset_{user.pk}'
            cached_data = cache.get(cache_key)

            if not cached_data:
                return Response(
                    {'error': 'Reset code has expired. Please request a new one.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if cached_data['attempts'] >= 3:
                cache.delete(cache_key)
                return Response(
                    {'error': 'Too many failed attempts. Please request a new reset code.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if cached_data['code'] != code:
                cached_data['attempts'] += 1
                cache.set(cache_key, cached_data, timeout=900)
                return Response({
                    'error': 'Invalid reset code',
                    'attempts_remaining': 3 - cached_data['attempts'],
                }, status=status.HTTP_400_BAD_REQUEST)

            reset_token = default_token_generator.make_token(user)
            uidb64 = urlsafe_base64_encode(force_bytes(user.pk))

            reset_session_key = f'reset_session_{user.pk}'
            cache.set(reset_session_key, {
                'token': reset_token,
                'uidb64': uidb64,
                'verified': True,
            }, timeout=600)
            cache.delete(cache_key)

            return Response({
                'success': True,
                'message': 'Code verified successfully',
                'reset_token': reset_token,
                'uidb64': uidb64,
                'expires_in': '10 minutes',
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f'Error in code verification: {e}')
            return Response(
                {'error': 'Code verification failed. Please try again.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class SetNewPasswordAPIView(generics.GenericAPIView):
    serializer_class = SetNewPasswordSerializer

    @swagger_auto_schema(
        tags=['Authentication'],
        operation_summary='Set new password',
        operation_description=(
            'Final step of password reset. '
            'Provide the **reset_token** and **uidb64** from the previous step '
            'along with the new password.'
        ),
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['password', 'token', 'uidb64'],
            properties={
                'password': openapi.Schema(type=openapi.TYPE_STRING, format='password', description='New password (min 6 chars)'),
                'token':    openapi.Schema(type=openapi.TYPE_STRING, description='reset_token from verify-reset-code'),
                'uidb64':   openapi.Schema(type=openapi.TYPE_STRING, description='uidb64 from verify-reset-code'),
            },
        ),
        responses={
            200: openapi.Response('Password updated', schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    'success': openapi.Schema(type=openapi.TYPE_BOOLEAN),
                    'message': openapi.Schema(type=openapi.TYPE_STRING),
                    'user_id': openapi.Schema(type=openapi.TYPE_STRING, format='uuid'),
                    'email':   openapi.Schema(type=openapi.TYPE_STRING),
                },
            )),
            400: openapi.Response('Invalid / expired session', schema=_ERROR_SCHEMA),
        },
    )
    def patch(self, request):
        try:
            serializer = self.serializer_class(data=request.data)
            serializer.is_valid(raise_exception=True)

            uidb64 = request.data.get('uidb64')
            user_id = force_str(urlsafe_base64_decode(uidb64))
            user = User.objects.get(pk=user_id)

            reset_session_key = f'reset_session_{user.pk}'
            session_data = cache.get(reset_session_key)
            if not session_data or not session_data.get('verified'):
                return Response(
                    {'error': 'Reset session expired. Please verify your code again.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            cache.delete(reset_session_key)
            return Response({
                'success': True,
                'message': 'Password reset successful',
                'user_id': str(user.id),
                'email': user.email,
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f'Error in password reset completion: {e}')
            return Response(
                {'error': 'Password reset failed. Please try again.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class TeamListView(generics.ListAPIView):
    """List staff members belonging to the current user's store."""
    serializer_class = TeamMemberSerializer
    permission_classes = [IsOwnerOrManager]

    def get_queryset(self):
        return User.objects.filter(store=self.request.user.store).order_by('-created_at')

    @swagger_auto_schema(
        tags=['Team'],
        operation_summary='List staff members',
        operation_description='Lists all users belonging to the current store. Owner/Manager only.',
        responses={200: TeamMemberSerializer(many=True)},
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class TeamInviteView(generics.GenericAPIView):
    """Invite a new staff member into the current owner's store."""
    serializer_class = TeamMemberInviteSerializer
    permission_classes = [IsOwner]

    @swagger_auto_schema(
        tags=['Team'],
        operation_summary='Invite a staff member',
        operation_description=(
            "Owner-only. Creates a new user scoped to the owner's store and emails them "
            'a 6-digit verification code (same flow as self-registration). The invitee '
            'completes setup via POST /auth/verify-email/, then sets their own password '
            'via PATCH /auth/change-password/.'
        ),
        request_body=TeamMemberInviteSerializer,
        responses={
            201: openapi.Response('Staff member created — verification email sent', schema=TeamMemberSerializer),
            400: openapi.Response('Validation error', schema=_ERROR_SCHEMA),
            500: openapi.Response('Email send failed', schema=_ERROR_SCHEMA),
        },
    )
    def post(self, request):
        try:
            serializer = self.serializer_class(data=request.data, context={'request': request})
            serializer.is_valid(raise_exception=True)
            user = serializer.save()

            verification_code = generate_token_code()
            cache_key = f'email_verification_{user.pk}'
            cache.set(cache_key, {
                'code': verification_code,
                'user_id': user.pk,
                'attempts': 0,
                'email': user.email,
            }, timeout=1800)

            store_name = request.user.store.name if request.user.store else 'your store'
            email_body = (
                f'Hello {user.name},\n\n'
                f'You have been added to {store_name} on LOGS.\n\n'
                f'Your email verification code is: {verification_code}\n\n'
                'This code will expire in 30 minutes. After verifying, set your password '
                'from the app.\n\n'
                'Best regards,\nLOGS Team'
            )
            email_sent = Util.send_email({
                'email_body': email_body,
                'to_email': user.email,
                'email_subject': 'You have been invited to join your team on LOGS',
            })

            if not email_sent:
                logger.warning(f'Failed to send invite email to {user.email}')
                cache.delete(cache_key)
                return Response(
                    {'error': 'Failed to send invite email. Please try again.'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            return Response(TeamMemberSerializer(user).data, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f'Error inviting team member: {e}', exc_info=True)
            return Response(
                {'error': f'Invite failed: {e}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class TeamMemberUpdateView(generics.GenericAPIView):
    """Update a staff member's role or active status."""
    serializer_class = TeamMemberUpdateSerializer
    permission_classes = [IsOwner]

    def get_object(self, pk):
        return User.objects.get(pk=pk, store=self.request.user.store)

    @swagger_auto_schema(
        tags=['Team'],
        operation_summary='Update a staff member',
        operation_description="Owner-only. Update role and/or active status for a user in the owner's store.",
        request_body=TeamMemberUpdateSerializer,
        responses={
            200: openapi.Response('Updated', schema=TeamMemberSerializer),
            404: openapi.Response('Not found', schema=_ERROR_SCHEMA),
        },
    )
    def patch(self, request, pk):
        try:
            user = self.get_object(pk)
        except User.DoesNotExist:
            return Response({'error': 'Staff member not found'}, status=status.HTTP_404_NOT_FOUND)

        serializer = self.serializer_class(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(TeamMemberSerializer(user).data, status=status.HTTP_200_OK)


class ChangePasswordView(generics.GenericAPIView):
    """Self-service password change for the current user."""
    serializer_class = ChangePasswordSerializer
    permission_classes = [permissions.IsAuthenticated]

    @swagger_auto_schema(
        tags=['Authentication'],
        operation_summary='Change password',
        operation_description=(
            'Self-service password change. If the account already has a usable password, '
            '**old_password** must be supplied and correct. Newly-invited staff who have '
            'not yet set a password may omit it.'
        ),
        request_body=ChangePasswordSerializer,
        responses={
            200: openapi.Response('Password updated', schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={'message': openapi.Schema(type=openapi.TYPE_STRING)},
            )),
            400: openapi.Response('Validation error', schema=_ERROR_SCHEMA),
        },
    )
    def patch(self, request):
        serializer = self.serializer_class(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({'message': 'Password updated successfully'}, status=status.HTTP_200_OK)


class LogoutAPIView(generics.GenericAPIView):
    serializer_class = LogoutSerializer
    permission_classes = (permissions.IsAuthenticated,)

    @swagger_auto_schema(
        tags=['Authentication'],
        operation_summary='Logout',
        operation_description='Blacklists the provided refresh token, invalidating it for future use.',
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['refresh'],
            properties={'refresh': openapi.Schema(type=openapi.TYPE_STRING, description='Refresh token to blacklist')},
        ),
        responses={
            200: openapi.Response('Logged out', schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={'message': openapi.Schema(type=openapi.TYPE_STRING)},
            )),
            400: openapi.Response('Invalid or already-blacklisted token', schema=_ERROR_SCHEMA),
        },
    )
    def post(self, request):
        try:
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response({'message': 'Successfully logged out'}, status=status.HTTP_200_OK)
        except Exception:
            return Response({'error': 'Logout failed'}, status=status.HTTP_400_BAD_REQUEST)
