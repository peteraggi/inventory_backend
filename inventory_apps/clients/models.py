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
