import re
from rest_framework import serializers
from .models import Client, Domain, SubscriptionPlan, WaitlistSignup


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionPlan
        fields = [
            'id', 'name', 'display_name', 'price_monthly',
            'max_stores', 'max_users', 'max_products', 'features',
        ]


class OnboardingSerializer(serializers.Serializer):
    business_name = serializers.CharField(max_length=255)
    contact_name = serializers.CharField(max_length=255)
    contact_email = serializers.EmailField()
    contact_phone = serializers.CharField(max_length=50, required=False, allow_blank=True, default='')
    password = serializers.CharField(
        min_length=6, max_length=68, write_only=True,
        style={'input_type': 'password'}
    )
    subdomain = serializers.CharField(max_length=63)
    plan = serializers.ChoiceField(
        choices=['free', 'basic', 'standard', 'enterprise'],
        default='free'
    )
    store_name = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')

    def validate_contact_email(self, value):
        from inventory_apps.authentication.models import User
        value = value.lower().strip()
        if User.objects.filter(email=value).exists() or Client.objects.filter(contact_email=value).exists():
            raise serializers.ValidationError(
                'An account already uses this email. Sign in instead, or use a different email.'
            )
        return value

    def validate_subdomain(self, value):
        from inventory_apps.clients.onboarding import schema_exists, schema_name_for
        value = value.lower().strip()
        if not re.match(r'^[a-z][a-z0-9\-]{1,61}[a-z0-9]$', value):
            raise serializers.ValidationError(
                'Use 3 to 63 letters, digits or hyphens, starting with a letter and not ending in a hyphen.'
            )
        if Domain.objects.filter(domain__istartswith=f'{value}.').exists() or schema_exists(schema_name_for(value)):
            raise serializers.ValidationError('That web address is already taken. Please choose another.')
        return value

    def validate_business_name(self, value):
        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError('Business name must be at least 2 characters.')
        return value

    def validate_contact_name(self, value):
        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError('Contact name must be at least 2 characters.')
        return value


class ClientDetailSerializer(serializers.ModelSerializer):
    plan = SubscriptionPlanSerializer(read_only=True)
    subdomain = serializers.SerializerMethodField()

    class Meta:
        model = Client
        fields = [
            'id', 'name', 'contact_name', 'contact_email', 'contact_phone',
            'schema_name', 'subdomain', 'plan', 'paid_until',
            'on_trial', 'trial_ends', 'is_active', 'created_at',
        ]

    def get_subdomain(self, obj):
        domain = obj.domains.filter(is_primary=True).first()
        return domain.domain if domain else None


class WaitlistSignupSerializer(serializers.ModelSerializer):
    class Meta:
        model = WaitlistSignup
        fields = ['id', 'email', 'name', 'business_name', 'whatsapp', 'reason', 'created_at']
        read_only_fields = ['id', 'created_at']

    def validate_email(self, value):
        return value.lower().strip()
