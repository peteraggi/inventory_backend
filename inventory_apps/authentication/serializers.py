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
            from inventory_apps.clients.workspaces import link_user
            link_user(user, store_id=validated_data['store'].id, role_id=validated_data['role'].id)
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
            user.save(skip_validation=True, update_fields=['password'])

            # Clear reset session
            cache.delete(reset_session_key)

            return attrs

        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            raise AuthenticationFailed('The reset link is invalid', 401)
        except Exception as e:
            raise AuthenticationFailed(f'Password reset failed: {str(e)}', 401)


class TeamMemberSerializer(serializers.ModelSerializer):
    """Read-only representation of a staff member for the team management screen."""
    role_id = serializers.UUIDField(read_only=True)
    role_name = serializers.CharField(source='role.display_name', read_only=True)
    store_id = serializers.UUIDField(read_only=True)
    roles = serializers.SerializerMethodField()
    additional_role_ids = serializers.SerializerMethodField()
    is_active = serializers.SerializerMethodField()
    permission_overrides = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'name', 'email', 'phone',
            'role_id', 'role_name', 'store_id',
            'roles', 'additional_role_ids',
            'is_active', 'is_verified', 'created_at',
            'permission_overrides',
        ]
        read_only_fields = fields

    def get_additional_role_ids(self, obj):
        from inventory_apps.authentication.rbac import extra_role_assignments
        return [str(a.role_id) for a in extra_role_assignments(obj)]

    def get_roles(self, obj):
        from inventory_apps.authentication.rbac import active_roles
        return [
            {'id': str(role.id), 'name': role.name, 'display_name': role.display_name}
            for role in active_roles(obj)
        ]

    def get_permission_overrides(self, obj):
        from inventory_apps.clients.workspaces import membership_for_current
        membership = membership_for_current(obj)
        return membership.permission_overrides if membership else obj.permission_overrides

    def get_is_active(self, obj):
        from inventory_apps.clients.workspaces import membership_for_current
        membership = membership_for_current(obj)
        return membership.is_active if membership else obj.is_active


def _check_team_grants(request, grants):
    """Managers may only grant what they hold themselves; owners hold everything."""
    from inventory_apps.authentication.rbac import grants_within, validate_matrix
    problems = validate_matrix(grants)
    if problems:
        raise serializers.ValidationError(problems)
    missing = grants_within(request.user, grants)
    if missing:
        raise serializers.ValidationError(
            f"You cannot grant permissions you do not hold: {', '.join(missing)}."
        )


def _check_owner_role(request, role):
    """Assigning a role gives its permissions, so the assigner must hold all of them."""
    from inventory_apps.authentication.rbac import role_grants_within
    # Roles that can change settings are refused unless the assigner holds settings update too.
    missing = role_grants_within(request.user, role)
    if missing:
        raise serializers.ValidationError(
            f"You cannot assign the {role.display_name} role: it includes permissions you do not hold."
        )


def _validate_additional_roles(request, role_ids, primary_id=None):
    """Each extra role must exist, be assignable by the requester, and not repeat the primary role."""
    roles = []
    for role_id in dict.fromkeys(role_ids):
        if str(role_id) == str(primary_id):
            continue
        role = Role.objects.filter(id=role_id).first()
        if role is None:
            raise serializers.ValidationError(f'Invalid role ID: {role_id}.')
        _check_owner_role(request, role)
        roles.append(role)
    return roles


def _sync_additional_roles(user, roles, assigned_by):
    """
    Make the user's extra roles in this business exactly `roles`. Removed roles are revoked,
    not deleted, so the history of who held what is kept.
    """
    from django.utils import timezone
    from inventory_apps.authentication.models import UserRole
    from inventory_apps.authentication.rbac import extra_role_assignments
    from inventory_apps.clients.workspaces import current_client

    client = current_client()
    workspace_id = client.pk if client else None
    wanted = {role.id for role in roles}
    current = extra_role_assignments(user)
    for assignment in current:
        if assignment.role_id not in wanted:
            assignment.unassigned_at = timezone.now()
            assignment.save(update_fields=['unassigned_at'])
    held = {assignment.role_id for assignment in current if assignment.unassigned_at is None}
    for role in roles:
        if role.id not in held:
            UserRole.objects.create(
                user=user, role=role, assigned_by=assigned_by, workspace_id=workspace_id,
            )


class TeamMemberInviteSerializer(serializers.Serializer):
    """Serializer for an owner or manager inviting a new staff member into their store."""
    name = serializers.CharField()
    email = serializers.EmailField()
    phone = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    role_id = serializers.UUIDField()
    additional_role_ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)
    permission_overrides = serializers.JSONField(required=False, default=dict)

    class Meta:
        fields = ['name', 'email', 'phone', 'role_id', 'additional_role_ids', 'permission_overrides']

    def validate_additional_role_ids(self, value):
        self._extra_roles = _validate_additional_roles(self.context['request'], value, self.initial_data.get('role_id'))
        return value

    def validate_permission_overrides(self, value):
        from inventory_apps.authentication.rbac import only_true
        _check_team_grants(self.context['request'], value)
        return only_true(value)

    def validate_name(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError('Name is required and cannot be empty.')
        return value.strip()

    def validate_email(self, value):
        email = value.lower().strip()
        if User.objects.filter(email=email).exists():
            raise serializers.ValidationError('A user with this email already exists.')
        return email

    def validate_role_id(self, value):
        role = Role.objects.filter(id=value).first()
        if role is None:
            raise serializers.ValidationError('Invalid role ID.')
        _check_owner_role(self.context['request'], role)
        return value

    def create(self, validated_data):
        request = self.context['request']
        role = Role.objects.get(id=validated_data['role_id'])
        user = User.objects.create_user(
            name=validated_data['name'],
            email=validated_data['email'],
            password=None,  # unusable until the invitee sets one via change-password
            phone=validated_data.get('phone'),
            store=request.user.store,
            role=role,
        )
        from inventory_apps.clients.workspaces import link_user
        link_user(
            user,
            store_id=request.user.store_id,
            role_id=role.id,
            permission_overrides=validated_data.get('permission_overrides', {}),
        )
        _sync_additional_roles(user, getattr(self, '_extra_roles', []), request.user)
        return user


class TeamMemberUpdateSerializer(serializers.Serializer):
    """Serializer for an owner or manager updating a staff member's roles, status or permissions."""
    role_id = serializers.UUIDField(required=False)
    additional_role_ids = serializers.ListField(child=serializers.UUIDField(), required=False)
    is_active = serializers.BooleanField(required=False)
    permission_overrides = serializers.JSONField(required=False)

    class Meta:
        fields = ['role_id', 'additional_role_ids', 'is_active', 'permission_overrides']

    def validate_additional_role_ids(self, value):
        primary = self.initial_data.get('role_id') or (self.instance.role_id if self.instance else None)
        self._extra_roles = _validate_additional_roles(self.context['request'], value, primary)
        return value

    def validate_role_id(self, value):
        role = Role.objects.filter(id=value).first()
        if role is None:
            raise serializers.ValidationError('Invalid role ID.')
        _check_owner_role(self.context['request'], role)
        return value

    def validate_permission_overrides(self, value):
        from inventory_apps.authentication.rbac import only_true
        _check_team_grants(self.context['request'], value)
        return only_true(value)

    def update(self, instance, validated_data):
        from inventory_apps.clients.workspaces import membership_for_current
        # Role, status and grants are per business: they live on this business's membership.
        membership = membership_for_current(instance)
        if 'role_id' in validated_data:
            membership.role_id = validated_data['role_id']
        if 'is_active' in validated_data:
            membership.is_active = validated_data['is_active']
        if 'permission_overrides' in validated_data:
            membership.permission_overrides = validated_data['permission_overrides']
        membership.save()
        if 'additional_role_ids' in validated_data:
            _sync_additional_roles(instance, self._extra_roles, self.context['request'].user)
        return instance


class MeSerializer(serializers.ModelSerializer):
    """Self-service profile for the logged-in user, including their signature."""
    role_name = serializers.CharField(source='role.display_name', read_only=True)
    store_name = serializers.CharField(source='store.name', read_only=True)
    role_key = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()
    roles = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'name', 'email', 'phone', 'bio', 'signature',
            'role_name', 'role_key', 'roles', 'permissions', 'store_name', 'created_at',
        ]
        read_only_fields = ['id', 'email', 'role_name', 'role_key', 'roles', 'permissions', 'store_name', 'created_at']

    def get_roles(self, obj):
        from inventory_apps.authentication.rbac import active_roles
        return [{'id': str(r.id), 'name': r.name, 'display_name': r.display_name} for r in active_roles(obj)]

    def get_role_key(self, obj):
        return obj.role.name if obj.role_id else ""

    def get_permissions(self, obj):
        from inventory_apps.authentication.rbac import effective_matrix
        return effective_matrix(obj)


class ChangePasswordSerializer(serializers.Serializer):
    """Self-service password change. old_password is required unless the account
    doesn't have a usable password yet (newly-invited staff)."""
    old_password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    new_password = serializers.CharField(min_length=6, write_only=True)

    class Meta:
        fields = ['old_password', 'new_password']

    def validate(self, attrs):
        user = self.context['request'].user
        if user.has_usable_password():
            old_password = attrs.get('old_password')
            if not old_password or not user.check_password(old_password):
                raise serializers.ValidationError({'old_password': 'Current password is incorrect.'})
        return attrs

    def save(self):
        user = self.context['request'].user
        user.set_password(self.validated_data['new_password'])
        user.save()
        return user


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