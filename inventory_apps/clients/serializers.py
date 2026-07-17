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
        value = value.lower().strip()
        if Client.objects.filter(contact_email=value).exists():
            raise serializers.ValidationError('An account with this email already exists.')
        return value

    def validate_subdomain(self, value):
        value = value.lower().strip()
        if not re.match(r'^[a-z][a-z0-9\-]{1,61}[a-z0-9]$', value):
            raise serializers.ValidationError(
                'Subdomain must start with a letter, use only letters/digits/hyphens, '
                'and be between 3 and 63 characters.'
            )
        if Domain.objects.filter(domain__istartswith=f'{value}.').exists():
            raise serializers.ValidationError('This subdomain is already taken.')
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
