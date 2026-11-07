import re
import logging
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from rest_framework import views, generics, status, permissions
from rest_framework.response import Response
from django.db import IntegrityError
from django_tenants.utils import schema_context
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi

from .models import Client, Domain, SubscriptionPlan, WaitlistSignup
from .serializers import (
    OnboardingSerializer,
    SubscriptionPlanSerializer,
    ClientDetailSerializer,
    WaitlistSignupSerializer,
)

logger = logging.getLogger(__name__)

from inventory_apps.erp_base.rbac_constants import DEFAULT_ROLE_PERMISSIONS
from inventory_apps.clients.onboarding import discard_partial_setup, schema_name_for

DEFAULT_ROLES = [
    {
        "name": "owner",
        "display_name": "Store Owner",
        "description": "Full access to all store operations",
        "permissions": {
            "manage_users": True,
            "manage_products": True,
            "manage_invoices": True,
            "view_reports": True,
            "manage_store": True,
        },
    },
    {
        "name": "manager",
        "display_name": "Store Manager",
        "description": "Manage products, invoices, and view reports",
        "permissions": {
            "manage_users": False,
            "manage_products": True,
            "manage_invoices": True,
            "view_reports": True,
            "manage_store": False,
        },
    },
    {
        "name": "salesperson",
        "display_name": "Salesperson",
        "description": "Create and manage own sales",
        "permissions": {
            "manage_users": False,
            "manage_products": False,
            "manage_invoices": True,
            "view_reports": False,
            "manage_store": False,
        },
    },
]


DEFAULT_ACCOUNTS = [
    # Assets
    {"code": "1000", "name": "Cash on Hand", "account_type": "asset"},
    {"code": "1010", "name": "Bank Account", "account_type": "asset"},
    {"code": "1100", "name": "Accounts Receivable", "account_type": "asset"},
    {"code": "1200", "name": "Inventory Asset", "account_type": "asset"},
    # Liabilities
    {"code": "2000", "name": "Accounts Payable", "account_type": "liability"},
    {"code": "2100", "name": "VAT Payable", "account_type": "liability"},
    # Equity
    {"code": "3000", "name": "Owner's Capital", "account_type": "equity"},
    {"code": "3100", "name": "Retained Earnings", "account_type": "equity"},
    # Revenue
    {"code": "4000", "name": "Sales Revenue", "account_type": "revenue"},
    # COGS
    {"code": "5000", "name": "Cost of Goods Sold", "account_type": "cogs"},
    # Expenses
    {"code": "6000", "name": "General Expenses", "account_type": "expense"},
    {"code": "6100", "name": "Operating Expenses", "account_type": "expense"},
]


def _seed_tenant(
    schema_name, store_name, owner_name, owner_email, owner_password, owner_phone
):
    """
    Creates default roles, chart of accounts, journals, a first store,
    and the owner account, then returns JWT tokens for the owner.
    """
    from inventory_apps.pos_app.models import Store, Role, Account, Journal
    from inventory_apps.authentication.models import User

    with schema_context(schema_name):
        # ── Roles ────────────────────────────────────────────────────────────
        owner_role = None
        for role_data in DEFAULT_ROLES:
            role, _ = Role.objects.get_or_create(
                name=role_data["name"],
                defaults={
                    "display_name": role_data["display_name"],
                    "description": role_data["description"],
                    "permissions": DEFAULT_ROLE_PERMISSIONS.get(role_data["name"], {}),
                },
            )
            if role_data["name"] == "owner":
                owner_role = role

        # ── Store ─────────────────────────────────────────────────────────────
        store_code = re.sub(r"[^A-Z0-9]", "", schema_name.upper())[:10] or "STORE001"
        store = Store.objects.create(name=store_name, code=store_code, currency="NGN")

        # ── Chart of Accounts ─────────────────────────────────────────────────
        accounts = {}
        for acc in DEFAULT_ACCOUNTS:
            obj, _ = Account.objects.get_or_create(
                store=store,
                code=acc["code"],
                defaults={
                    "name": acc["name"],
                    "account_type": acc["account_type"],
                    "is_system": True,
                },
            )
            accounts[acc["code"]] = obj

        # ── Journals ──────────────────────────────────────────────────────────
        Journal.objects.get_or_create(
            store=store,
            code="SALE",
            defaults={
                "name": "Sales Journal",
                "journal_type": "sale",
                "default_debit_account": accounts.get("1100"),  # AR
                "default_credit_account": accounts.get("4000"),  # Revenue
            },
        )
        Journal.objects.get_or_create(
            store=store,
            code="PURCH",
            defaults={
                "name": "Purchase Journal",
                "journal_type": "purchase",
                "default_debit_account": accounts.get("1200"),  # Inventory
                "default_credit_account": accounts.get("2000"),  # AP
            },
        )
        Journal.objects.get_or_create(
            store=store,
            code="CASH",
            defaults={
                "name": "Cash Journal",
                "journal_type": "cash",
                "default_debit_account": accounts.get("1000"),
                "default_credit_account": accounts.get("1100"),
            },
        )
        Journal.objects.get_or_create(
            store=store,
            code="BANK",
            defaults={
                "name": "Bank Journal",
                "journal_type": "bank",
                "default_debit_account": accounts.get("1010"),
                "default_credit_account": accounts.get("1100"),
            },
        )
        Journal.objects.get_or_create(
            store=store,
            code="INV",
            defaults={
                "name": "Inventory Valuation",
                "journal_type": "inventory",
                "default_debit_account": accounts.get("5000"),  # COGS
                "default_credit_account": accounts.get("1200"),  # Inventory Asset
            },
        )

        # ── Owner user ────────────────────────────────────────────────────────
        user = User.objects.create_user(
            name=owner_name,
            email=owner_email,
            password=owner_password,
            phone=owner_phone or None,
            store=store,
            role=owner_role,
        )
        user.is_verified = True
        user.save(skip_validation=True)

        from inventory_apps.clients.workspaces import link_user
        link_user(
            user,
            store_id=store.id,
            role_id=owner_role.id if owner_role else None,
            client=Client.objects.get(schema_name=schema_name),
        )
        return user.tokens()


# ─── Reusable schema fragments ────────────────────────────────────────────────

_TOKEN_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    properties={
        "access": openapi.Schema(type=openapi.TYPE_STRING),
        "refresh": openapi.Schema(type=openapi.TYPE_STRING),
    },
)

_ERROR_SCHEMA = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    properties={"error": openapi.Schema(type=openapi.TYPE_STRING)},
)


class ListPlansAPIView(generics.ListAPIView):
    """Public endpoint — returns all active subscription plans."""

    serializer_class = SubscriptionPlanSerializer
    permission_classes = [permissions.AllowAny]
    queryset = SubscriptionPlan.objects.filter(is_active=True)

    @swagger_auto_schema(
        tags=["Onboarding"],
        operation_summary="List subscription plans",
        operation_description="Returns all active plans. Use this before the onboarding step to show pricing to prospective customers.",
        responses={200: SubscriptionPlanSerializer(many=True)},
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class OnboardingAPIView(views.APIView):
    permission_classes = [permissions.AllowAny]

    @swagger_auto_schema(
        tags=["Onboarding"],
        operation_summary="Register a new business (self-service)",
        operation_description=(
            "Creates a new tenant (isolated PostgreSQL schema), seeds default roles and a first store, "
            "and provisions an owner account in a single request. "
            "The owner is logged in immediately — use the returned JWT tokens for all subsequent calls "
            "on `{subdomain}.api.logsng.tech`.\n\n"
            '**`plan`** defaults to `"free"` (30-day trial). '
            "**`store_name`** defaults to `business_name` if omitted."
        ),
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=[
                "business_name",
                "contact_name",
                "contact_email",
                "password",
                "subdomain",
            ],
            properties={
                "business_name": openapi.Schema(
                    type=openapi.TYPE_STRING, example="Acme Retail"
                ),
                "contact_name": openapi.Schema(
                    type=openapi.TYPE_STRING, example="John Doe"
                ),
                "contact_email": openapi.Schema(
                    type=openapi.TYPE_STRING, format="email", example="john@acme.com"
                ),
                "contact_phone": openapi.Schema(
                    type=openapi.TYPE_STRING, example="08012345678"
                ),
                "password": openapi.Schema(
                    type=openapi.TYPE_STRING, format="password", example="secret123"
                ),
                "subdomain": openapi.Schema(
                    type=openapi.TYPE_STRING,
                    example="acme",
                    description="3–63 chars, letters/digits/hyphens. Becomes acme.api.logsng.tech",
                ),
                "plan": openapi.Schema(
                    type=openapi.TYPE_STRING,
                    enum=["free", "basic", "standard", "enterprise"],
                    default="free",
                ),
                "store_name": openapi.Schema(
                    type=openapi.TYPE_STRING, example="Acme HQ"
                ),
            },
        ),
        responses={
            201: openapi.Response(
                description="Tenant created — owner is logged in",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        "success": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                        "message": openapi.Schema(type=openapi.TYPE_STRING),
                        "tenant": openapi.Schema(
                            type=openapi.TYPE_OBJECT,
                            properties={
                                "id": openapi.Schema(
                                    type=openapi.TYPE_STRING, format="uuid"
                                ),
                                "business_name": openapi.Schema(
                                    type=openapi.TYPE_STRING
                                ),
                                "subdomain": openapi.Schema(type=openapi.TYPE_STRING),
                                "api_base_url": openapi.Schema(
                                    type=openapi.TYPE_STRING
                                ),
                                "plan": openapi.Schema(type=openapi.TYPE_STRING),
                                "on_trial": openapi.Schema(type=openapi.TYPE_BOOLEAN),
                                "trial_ends": openapi.Schema(
                                    type=openapi.TYPE_STRING, format="date"
                                ),
                            },
                        ),
                        "owner": openapi.Schema(
                            type=openapi.TYPE_OBJECT,
                            properties={
                                "email": openapi.Schema(type=openapi.TYPE_STRING),
                                "name": openapi.Schema(type=openapi.TYPE_STRING),
                                "tokens": _TOKEN_SCHEMA,
                            },
                        ),
                    },
                ),
            ),
            400: openapi.Response(
                "Validation error (e.g. subdomain taken)", schema=_ERROR_SCHEMA
            ),
            500: openapi.Response("Tenant provisioning failed", schema=_ERROR_SCHEMA),
        },
    )
    def post(self, request):
        serializer = OnboardingSerializer(data=request.data)
        if not serializer.is_valid():
            field, messages = next(iter(serializer.errors.items()))
            return Response(
                {"success": False, "error": str(messages[0]), "field": field},
                status=status.HTTP_400_BAD_REQUEST,
            )
        data = serializer.validated_data

        subdomain = data["subdomain"]
        schema_name = schema_name_for(subdomain)
        full_domain = f"{subdomain}.{settings.BASE_DOMAIN}"
        store_name = data.get("store_name") or data["business_name"]
        email = data["contact_email"]

        client = None
        try:
            plan = SubscriptionPlan.objects.filter(
                name=data.get("plan", "free"), is_active=True
            ).first()

            trial_ends = (timezone.now() + timedelta(days=30)).date()

            client = Client(
                name=data["business_name"],
                schema_name=schema_name,
                contact_name=data["contact_name"],
                contact_email=email,
                contact_phone=data.get("contact_phone", ""),
                plan=plan,
                on_trial=True,
                trial_ends=trial_ends,
                approval_status="pending",
            )
            client.save()

            Domain.objects.create(domain=full_domain, tenant=client, is_primary=True)

            # The owner's account is created now, but no session is issued until a super admin approves the business.
            _seed_tenant(
                schema_name=schema_name,
                store_name=store_name,
                owner_name=data["contact_name"],
                owner_email=email,
                owner_password=data["password"],
                owner_phone=data.get("contact_phone", ""),
            )
        except IntegrityError:
            logger.exception("Onboarding for %s clashed with an existing record", subdomain)
            discard_partial_setup(client, schema_name, email)
            return Response(
                {
                    "success": False,
                    "error": "Those details were just taken by another registration. Check them and try again.",
                },
                status=status.HTTP_409_CONFLICT,
            )
        except Exception:
            logger.exception("Onboarding failed for %s", subdomain)
            discard_partial_setup(client, schema_name, email)
            return Response(
                {
                    "success": False,
                    "error": (
                        "We could not set up your business just now. Nothing was saved, "
                        "so you can try again in a few minutes."
                    ),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {
                "success": True,
                "pending_approval": True,
                "message": (
                    "Your business is registered and awaits approval from the platform team. "
                    "You can sign in once it is approved."
                ),
                "tenant": {
                    "id": str(client.id),
                    "business_name": client.name,
                    "subdomain": subdomain,
                    "api_base_url": f"https://{full_domain}",
                    "plan": plan.name if plan else "free",
                    "on_trial": True,
                    "trial_ends": str(trial_ends),
                },
                "owner": {"email": email, "name": data["contact_name"]},
            },
            status=status.HTTP_201_CREATED,
        )

class WaitlistSignupAPIView(generics.CreateAPIView):
    """Public endpoint — captures pre-launch email signups. Re-submitting the
    same email updates their reason/name instead of erroring."""

    serializer_class = WaitlistSignupSerializer
    permission_classes = [permissions.AllowAny]
    queryset = WaitlistSignup.objects.all()

    @swagger_auto_schema(
        tags=["Waitlist"],
        operation_summary="Join the waitlist",
        operation_description="Captures an email (plus optional name/business/reason) for early access.",
        responses={
            201: WaitlistSignupSerializer,
            200: WaitlistSignupSerializer,
        },
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        existing = WaitlistSignup.objects.filter(email=email).first()
        if existing:
            for field in ("name", "business_name", "whatsapp", "reason"):
                if serializer.validated_data.get(field):
                    setattr(existing, field, serializer.validated_data[field])
            existing.save()
            return Response(WaitlistSignupSerializer(existing).data, status=status.HTTP_200_OK)

        signup = serializer.save()
        return Response(WaitlistSignupSerializer(signup).data, status=status.HTTP_201_CREATED)


class WaitlistCountAPIView(views.APIView):
    """Public endpoint — total waitlist signups, for social-proof display."""

    permission_classes = [permissions.AllowAny]

    @swagger_auto_schema(
        tags=["Waitlist"],
        operation_summary="Get waitlist signup count",
        responses={200: openapi.Response(
            "Signup count",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={"count": openapi.Schema(type=openapi.TYPE_INTEGER)},
            ),
        )},
    )
    def get(self, request):
        return Response({"count": WaitlistSignup.objects.count()})
