# authentication/models.py

from django.db import models
from django.contrib.auth.models import (
    AbstractBaseUser, BaseUserManager, PermissionsMixin)
from rest_framework_simplejwt.tokens import RefreshToken
import uuid
import re


class UserManager(BaseUserManager):
    def _generate_username(self, name, email):
        """Generate a unique username"""
        base = re.sub(r'[^a-zA-Z0-9]', '', name.lower().replace(' ', '')) or email.split('@')[0].lower()
        username = base[:50]
        counter = 1
        while self.model.objects.filter(username=username).exists():
            username = f"{base}{counter}"
            counter += 1
        return username
    
    def create_user(self, name, email, password=None, store=None, role=None, **extra_fields):
        """
        Create and save a user with the given email, name, and password.
        """
        if not email:
            raise TypeError('Users must have an email address')
        if not name:
            raise TypeError('Users must have a name')

        # Normalize email
        email = self.normalize_email(email)

        # Generate username
        username = self._generate_username(name, email)

        # Create user instance
        user = self.model(
            username=username,
            email=email,
            name=name,
            store=store,
            role=role,
            **extra_fields
        )

        # Set password
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()

        user.save(using=self._db)
        return user
    
    def create_superuser(self, name, email, password=None, **extra_fields):
        """
        Create and save a superuser with the given email, name, and password.
        """
        if not password:
            raise TypeError('Superuser must have a password')

        # Set superuser defaults
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_verified', True)
        extra_fields.setdefault('is_active', True)

        # Create superuser without store/role requirements
        user = self.create_user(
            name=name,
            email=email,
            password=password,
            **extra_fields
        )

        return user

AUTH_PROVIDERS = {
    'facebook': 'facebook',
    'google': 'google',
    'twitter': 'twitter',
    'email': 'email',
    'apple': 'apple'
}


class User(AbstractBaseUser, PermissionsMixin):
    """
    Extended User model with store and role for POS system.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = models.CharField(max_length=255, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    email = models.EmailField(max_length=255, unique=True, db_index=True)
    phone = models.CharField(max_length=255, blank=True, null=True)
    bio = models.TextField(blank=True, null=True)
    # Store and Role are in pos_app (same tenant schema); string refs avoid circular imports
    store = models.ForeignKey(
        'pos_app.Store',
        on_delete=models.CASCADE,
        related_name='users',
        help_text='Store the user belongs to',
        null=True,
        blank=True,
        db_constraint=False,  # store lives in tenant schema; no cross-schema FK enforcement
    )
    role = models.ForeignKey(
        'pos_app.Role',
        on_delete=models.PROTECT,
        related_name='users',
        help_text="User's role in the system",
        null=True,
        blank=True,
        db_constraint=False,  # role lives in tenant schema; no cross-schema FK enforcement
    )

    # Status fields
    is_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
     # Authentication provider
    auth_provider = models.CharField(
        max_length=255,
        blank=False,
        null=False,
        default=AUTH_PROVIDERS.get('email')
    )

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['name']

    objects = UserManager()

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        indexes = [
            models.Index(fields=['email', 'is_active']),
            models.Index(fields=['store', 'role']),
        ]

    def __str__(self):
        """
        Safe string representation that handles None values.
        This fixes the AttributeError when store or role is None.
        """
        try:
            # Get name or email as identifier
            identifier = self.name or self.email or self.username or f"User {self.id}"

            # Safely get store name
            store_name = None
            if self.store is not None:
                store_name = getattr(self.store, 'name', None)

            # Safely get role name
            role_name = None
            if self.role is not None:
                role_name = getattr(self.role, 'name', None)

            # Build string representation
            if store_name and role_name:
                return f"{identifier} ({role_name} @ {store_name})"
            elif role_name:
                return f"{identifier} ({role_name})"
            elif store_name:
                return f"{identifier} @ {store_name}"
            else:
                return identifier

        except Exception:
            return f"User {getattr(self, 'id', '?')}"

    def clean(self):
        """
        Validate user data before saving.
        """
        from django.core.exceptions import ValidationError

        # Regular users (non-superusers) must have store and role
        if not self.is_superuser:
            if not self.store:
                raise ValidationError({
                    'store': 'Regular users must be assigned to a store.'
                })
            if not self.role:
                raise ValidationError({
                    'role': 'Regular users must have a role assigned.'
                })

        # Validate store is active
        if self.store and not self.store.is_active:
            raise ValidationError({
                'store': 'Cannot assign user to an inactive store.'
            })
    
    def save(self, *args, **kwargs):
        """
        Override save to ensure data integrity.
        """
        # Call clean for validation (unless skip_validation is passed)
        if not kwargs.pop('skip_validation', False):
            # Only validate for non-superusers
            if not self.is_superuser and not self.is_staff:
                self.full_clean()

        super().save(*args, **kwargs)

    def tokens(self):
        """
        Generate JWT tokens for the user.
        """
        refresh = RefreshToken.for_user(self)
        return {
            'refresh': str(refresh),
            'access': str(refresh.access_token)
        }

    @property
    def is_owner(self):
        """Check if user is a store owner."""
        return self.role and self.role.name == 'owner'

    @property
    def is_manager(self):
        """Check if user is a store manager."""
        return self.role and self.role.name == 'manager'

    @property
    def is_salesperson(self):
        """Check if user is a salesperson."""
        return self.role and self.role.name == 'salesperson'

    @property
    def role_display(self):
        """Get role display name safely."""
        if self.role:
            return getattr(self.role, 'display_name', None) or getattr(self.role, 'name', 'Unknown')
        return 'No Role'

    @property
    def store_display(self):
        """Get store display name safely."""
        if self.store:
            return getattr(self.store, 'name', 'Unknown Store')
        return 'No Store'

    def has_permission(self, permission_key):
        """
        Check if user has a specific permission.
        """
        if self.is_superuser:
            return True

        if not self.role:
            return False

        permissions = getattr(self.role, 'permissions', {})
        return permissions.get(permission_key, False)

    def get_full_name(self):
        """Return the user's full name."""
        return self.name

    def get_short_name(self):
        """Return the user's short name."""
        return self.name.split()[0] if self.name else self.username
