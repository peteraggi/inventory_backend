# authentication/serializers.py

from django.core.cache import cache
from rest_framework import serializers
from .models import User
from django.contrib import auth
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework_simplejwt.tokens import RefreshToken, TokenError
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode

from ..pos_app.models import Store, Role

class RegisterSerializer(serializers.ModelSerializer):
    """
    Serializer for user registration with store and role assignment.
    """
    password = serializers.CharField(
        max_length=68,
        min_length=6,
        write_only=True,
        style={'input_type': 'password'}
    )
    user_id = serializers.UUIDField(source='id', read_only=True)
    username = serializers.CharField(read_only=True)
    store_id = serializers.UUIDField(write_only=True, required=True)
    role_id = serializers.UUIDField(write_only=True, required=True)
    store_name = serializers.CharField(source='store.name', read_only=True)
    role_name = serializers.CharField(source='role.display_name', read_only=True)

    class Meta:
        model = User
        fields = [
            'email', 'name', 'password', 'phone',
            'store_id', 'role_id', 'user_id', 'username',
            'store_name', 'role_name'
        ]
        read_only_fields = ['user_id', 'username', 'store_name', 'role_name']
    
    def validate_email(self, value):
        """Validate and normalize email."""
        email = value.lower().strip()

        # Check if email already exists
        if User.objects.filter(email=email).exists():
            raise serializers.ValidationError('A user with this email already exists.')

        return email

    def validate_name(self, value):
        """Validate name."""
        if not value or not value.strip():
            raise serializers.ValidationError('Name is required and cannot be empty.')

        if len(value.strip()) < 2:
            raise serializers.ValidationError('Name must be at least 2 characters long.')

        return value.strip()

    def validate_password(self, value):
        """Validate password strength."""
        if len(value) < 6:
            raise serializers.ValidationError('Password must be at least 6 characters long.')

        # Optional: Add more password strength checks
        # if not any(char.isdigit() for char in value):
        #     raise serializers.ValidationError('Password must contain at least one digit.')

        return value
    
    def validate(self, attrs):
        """Cross-field validation."""
        email = attrs.get('email', '').lower()
        name = attrs.get('name', '')
        store_id = attrs.get('store_id')
        role_id = attrs.get('role_id')

        if not name:
            raise serializers.ValidationError({'name': 'Name is required'})
        if not email:
            raise serializers.ValidationError({'email': 'Email is required'})

        # Validate store exists and is active
        try:
            store = Store.objects.get(id=store_id, is_active=True)
            attrs['store'] = store
        except Store.DoesNotExist:
            raise serializers.ValidationError({
                'store_id': 'Invalid store ID or store is inactive.'
            })

        # Validate role exists
        try:
            role = Role.objects.get(id=role_id)
            attrs['role'] = role
        except Role.DoesNotExist:
            raise serializers.ValidationError({
                'role_id': 'Invalid role ID.'
            })

        return attrs
        
    def create(self, validated_data):
        """Create user with validated data."""
        # Remove IDs from validated_data (we already have the objects)
        validated_data.pop('store_id', None)
        validated_data.pop('role_id', None)

        try:
            user = User.objects.create_user(
                name=validated_data['name'],
                email=validated_data['email'],
                password=validated_data['password'],
                phone=validated_data.get('phone'),
                store=validated_data['store'],
                role=validated_data['role']
            )
            return user
        except Exception as e:
            raise serializers.ValidationError(f'Failed to create user: {str(e)}')


class LoginSerializer(serializers.ModelSerializer):
    """
    Serializer for user login with JWT token generation.
    """
    email = serializers.EmailField(max_length=255, min_length=3)
    password = serializers.CharField(
        max_length=68,
        min_length=6,
        write_only=True,
        style={'input_type': 'password'}
    )
    username = serializers.CharField(read_only=True)
    user_id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    store_id = serializers.UUIDField(read_only=True)
    store_name = serializers.CharField(read_only=True)
    role = serializers.CharField(read_only=True)
    tokens = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'email', 'name', 'password', 'username', 'user_id',
            'store_id', 'store_name', 'role', 'tokens'
        ]
        read_only_fields = [
            'name', 'username', 'user_id', 'store_id',
            'store_name', 'role', 'tokens'
        ]
    
    def get_tokens(self, obj):
        """Generate JWT tokens for user."""
        user = self.context.get('user')
        if not user:
            raise serializers.ValidationError("User not found in context")
        return user.tokens()
    
    def validate(self, attrs):
        """Validate login credentials."""
        email = attrs.get('email', '').lower().strip()
        password = attrs.get('password', '')

        if not email or not password:
            raise AuthenticationFailed('Email and password are required')

        # Check if user exists
        try:
            user_obj = User.objects.get(email=email)
        except User.DoesNotExist:
            raise AuthenticationFailed('Invalid credentials')

        # Check auth provider
        if user_obj.auth_provider != 'email':
            raise AuthenticationFailed(
                f'Please continue your login using {user_obj.auth_provider}'
            )

        # Authenticate
        user = auth.authenticate(email=email, password=password)
        if not user:
            raise AuthenticationFailed('Invalid credentials, try again')

        # Check account status
        if not user.is_active:
            raise AuthenticationFailed('Account disabled, contact admin')

        if not user.is_verified:
            raise AuthenticationFailed('Email is not verified')

        # Check store (only for non-superusers)
        if not user.is_superuser and not user.is_staff:
            if not user.store:
                raise AuthenticationFailed('User not assigned to any store')

            if not user.store.is_active:
                raise AuthenticationFailed('Store is inactive, contact admin')

            if not user.role:
                raise AuthenticationFailed('User has no role assigned')

        # Store user in context
        self.context['user'] = user
        return attrs

    def to_representation(self, instance):
        """Custom representation for login response."""
        user = self.context.get('user')
        if not user:
            raise serializers.ValidationError("User not found in context")

        # Safely get store and role information
        store_id = None
        store_name = None
        role_name = None

        if user.store:
            store_id = str(user.store.id)
            store_name = getattr(user.store, 'name', 'Unknown Store')

        if user.role:
            role_name = getattr(user.role, 'name', 'Unknown Role')

        return {
            'email': user.email,
            'name': user.name,
            'username': user.username,
            'user_id': str(user.id),
            'store_id': store_id,
            'store_name': store_name,
            'role': role_name,
            'tokens': self.get_tokens(user)
        }


class EmailVerificationSerializer(serializers.Serializer):
    """Serializer for email verification."""
    email = serializers.EmailField()
    code = serializers.CharField(min_length=6, max_length=6)

    class Meta:
        fields = ['email', 'code']

    def validate_code(self, value):
        """Validate verification code format."""
        if not value.isdigit():
            raise serializers.ValidationError("Code must contain only digits")
        if len(value) != 6:
            raise serializers.ValidationError("Code must be exactly 6 digits")
        return value

    def validate_email(self, value):
        """Normalize email."""
        return value.lower().strip()


class ResendVerificationCodeSerializer(serializers.Serializer):
    """Serializer for resending verification code."""
    email = serializers.EmailField()

    class Meta:
        fields = ['email']

    def validate_email(self, value):
        """Normalize email."""
        return value.lower().strip()


class ResetPasswordEmailRequestSerializer(serializers.Serializer):
    """Serializer for password reset request."""
    email = serializers.EmailField(min_length=2)

    class Meta:
        fields = ['email']

    def validate_email(self, value):
        """Normalize email."""
        return value.lower().strip()


class VerifyResetCodeSerializer(serializers.Serializer):
    """Serializer for verifying password reset code."""
    email = serializers.EmailField()
    code = serializers.CharField(min_length=6, max_length=6)

    class Meta:
        fields = ['email', 'code']

    def validate_code(self, value):
        """Validate reset code format."""
        if not value.isdigit():
            raise serializers.ValidationError("Code must contain only digits")
        if len(value) != 6:
            raise serializers.ValidationError("Code must be exactly 6 digits")
        return value

    def validate_email(self, value):
        """Normalize email."""
        return value.lower().strip()

class SetNewPasswordSerializer(serializers.Serializer):
    """Serializer for setting new password."""
    password = serializers.CharField(
        min_length=6,
        max_length=68,
        write_only=True,
        style={'input_type': 'password'}
    )
    token = serializers.CharField(min_length=1, write_only=True)
    uidb64 = serializers.CharField(min_length=1, write_only=True)

    class Meta:
        fields = ['password', 'token', 'uidb64']

    def validate_password(self, value):
        """Validate password strength."""
        if len(value) < 6:
            raise serializers.ValidationError(
                "Password must be at least 6 characters long"
            )
        return value

    def validate(self, attrs):
        """Validate and set new password."""
        try:
            password = attrs.get('password')
            token = attrs.get('token')
            uidb64 = attrs.get('uidb64')

            # Decode user ID
            user_id = force_str(urlsafe_base64_decode(uidb64))
            user = User.objects.get(pk=user_id)

            # Verify token
            if not default_token_generator.check_token(user, token):
                raise AuthenticationFailed(
                    'The reset token is invalid or expired', 401
                )

            # Check reset session
            reset_session_key = f"reset_session_{user.pk}"
            session_data = cache.get(reset_session_key)

            if not session_data or not session_data.get('verified'):
                raise AuthenticationFailed(
                    'Reset session expired. Please verify your code again.', 401
                )

            # Set new password
            user.set_password(password)
            user.save()

            # Clear reset session
            cache.delete(reset_session_key)

            return attrs

        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            raise AuthenticationFailed('The reset link is invalid', 401)
        except Exception as e:
            raise AuthenticationFailed(f'Password reset failed: {str(e)}', 401)


class LogoutSerializer(serializers.Serializer):
    """Serializer for user logout."""
    refresh = serializers.CharField()

    def validate(self, attrs):
        """Validate and blacklist refresh token."""
        refresh_token = attrs.get('refresh')

        if not refresh_token:
            raise serializers.ValidationError("Refresh token is required")

        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
            return attrs
        except TokenError:
            raise serializers.ValidationError("Token is expired or invalid")
        except Exception as e:
            raise serializers.ValidationError(f"Logout failed: {str(e)}")

    def save(self, **kwargs):
        """No-op save method."""
        pass