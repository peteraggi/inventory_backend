from django.conf import settings
from django.db import models
from django_tenants.models import TenantMixin, DomainMixin
from decimal import Decimal
import uuid


class SubscriptionPlan(models.Model):
    PLAN_CHOICES = (
        ('free', 'Free Trial'),
        ('basic', 'Basic'),
        ('standard', 'Standard'),
        ('enterprise', 'Enterprise'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=50, choices=PLAN_CHOICES, unique=True)
    display_name = models.CharField(max_length=100)
    price_monthly = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text='Monthly price in NGN'
    )
    max_stores = models.IntegerField(default=1)
    max_users = models.IntegerField(default=5)
    max_products = models.IntegerField(default=100)
    features = models.JSONField(default=dict, help_text='Feature flags for this plan')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.display_name


class Client(TenantMixin):
    """
    One Client = one business/company = one PostgreSQL schema.
    schema_name is derived from the chosen subdomain (e.g. 'acme_retail').
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, help_text='Business / company name')
    contact_name = models.CharField(max_length=255)
    contact_email = models.EmailField(unique=True)
    contact_phone = models.CharField(max_length=50, blank=True)

    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='clients'
    )
    paid_until = models.DateField(null=True, blank=True)
    on_trial = models.BooleanField(default=True)
    trial_ends = models.DateField(null=True, blank=True)
    # New sign-ups are set to 'pending' by onboarding; a super admin approves them.
    # The default is 'approved' so businesses created by hand (admin, tests) work straight away.
    APPROVAL_CHOICES = (
        ('pending', 'Awaiting approval'),
        ('approved', 'Approved'),
    )
    approval_status = models.CharField(max_length=20, choices=APPROVAL_CHOICES, default='approved', db_index=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.EmailField(blank=True, help_text='Super admin who approved the business')
    # A super admin can deactivate a business; nobody in it can use it until it is reactivated.
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Tells django-tenants to create + migrate the schema automatically on save
    auto_create_schema = True

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.schema_name})'


class Domain(DomainMixin):
    """Maps a subdomain to a Client tenant."""
    pass


class WaitlistSignup(models.Model):
    """Pre-launch / early-access signups captured from the public landing page."""

    REASON_CHOICES = (
        ('retailer', 'Running a retail or wholesale business'),
        ('distributor', 'Running a distribution or logistics business'),
        ('developer', "I'm interested in the API"),
        ('other', 'Something else'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=255, blank=True)
    business_name = models.CharField(max_length=255, blank=True)
    whatsapp = models.CharField(max_length=50, blank=True)
    reason = models.CharField(max_length=20, choices=REASON_CHOICES, default='other')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.email


class WorkspaceMembership(models.Model):
    """
    A user's place in one business (Client). The user table is shared across the platform,
    but a store and role only mean something inside one business's schema, so each business
    a person belongs to gets its own row with that business's store and role.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='workspace_memberships',
    )
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='memberships')
    store_id = models.UUIDField(null=True, blank=True, help_text="Store in this business's schema")
    role_id = models.UUIDField(null=True, blank=True, help_text="Role in this business's schema")
    permission_overrides = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'client'], name='uniq_workspace_membership'),
        ]

    def __str__(self):
        return f"{self.user_id} @ {self.client_id}"
