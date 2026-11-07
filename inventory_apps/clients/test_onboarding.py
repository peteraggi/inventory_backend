# inventory_apps/clients/test_onboarding.py
"""
Registering a business: taken details are refused with a plain message naming the field, and a
registration that fails part-way leaves nothing behind, so the same details can be tried again.
"""
from unittest import mock

from django.test import RequestFactory
from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import get_public_schema_name, schema_context

from inventory_apps.authentication.models import User
from inventory_apps.clients.models import Client, Domain
from inventory_apps.clients.onboarding import schema_exists
from inventory_apps.clients.views import OnboardingAPIView


class OnboardingTests(TenantTestCase):

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()
        with schema_context(get_public_schema_name()):
            User.objects.create_user(name="Existing", email="taken@acme.test", password="pass1234", is_staff=True)

    def register(self, **overrides):
        details = {
            "business_name": "Acme Traders", "contact_name": "Ada Owner",
            "contact_email": "new-owner@acme.test", "password": "pass1234",
            "subdomain": "acme-traders", "plan": "free",
        }
        details.update(overrides)
        request = self.factory.post("/platform/onboard/", details, content_type="application/json")
        with schema_context(get_public_schema_name()):
            return OnboardingAPIView.as_view()(request)

    def test_an_email_that_already_has_an_account_is_refused_in_plain_words(self):
        response = self.register(contact_email="taken@acme.test")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["field"], "contact_email")
        self.assertEqual(
            response.data["error"],
            "An account already uses this email. Sign in instead, or use a different email.",
        )

    def test_a_taken_web_address_is_refused_and_named(self):
        with schema_context(get_public_schema_name()):
            first = Client(schema_name="taken_address", name="First", contact_name="X",
                           contact_email="first@acme.test")
            first.auto_create_schema = False
            first.save()
            Domain.objects.create(domain="acme-taken.lvh.me", tenant=first, is_primary=True)

        response = self.register(subdomain="acme-taken")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["field"], "subdomain")
        self.assertIn("already taken", response.data["error"])

    def test_a_failed_registration_leaves_nothing_behind_so_it_can_be_retried(self):
        with mock.patch("inventory_apps.clients.views._seed_tenant", side_effect=RuntimeError("boom")):
            response = self.register()

        self.assertEqual(response.status_code, 500)
        self.assertNotIn("boom", response.data["error"])
        self.assertNotIn("duplicate", response.data["error"].lower())
        with schema_context(get_public_schema_name()):
            self.assertFalse(Client.objects.filter(schema_name="acme_traders").exists())
        self.assertFalse(User.objects.filter(email="new-owner@acme.test").exists())
        self.assertFalse(schema_exists("acme_traders"))
