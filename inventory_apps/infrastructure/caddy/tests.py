"""
Unit tests for the Caddy TLS-ask integration.

These tests bypass Django's URL routing and middleware stack and call the view
directly via RequestFactory.  This avoids complications with django-tenants'
TenantMainMiddleware, which rewrites the URL conf based on the Host header.

The database is never touched: the Domain model query is patched with
unittest.mock so tests run fast and without migrations or a real schema.
"""

from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase, override_settings

from inventory_apps.infrastructure.caddy.services import CaddyTlsAskService
from inventory_apps.infrastructure.caddy.views import tls_ask

_PATCH_TARGET = "inventory_apps.infrastructure.caddy.services.get_tenant_domain_model"
_PARENT = "api.logsng.tech"


def _mock_domain_model(*, exists: bool) -> MagicMock:
    """Return a mock Domain model whose ``.filter().exists()`` returns *exists*."""
    model = MagicMock()
    model.objects.filter.return_value.exists.return_value = exists
    return model


class TlsAskServiceTests(SimpleTestCase):
    """Unit tests for CaddyTlsAskService.evaluate()."""

    def setUp(self):
        self.service = CaddyTlsAskService()

    # ── happy path ────────────────────────────────────────────────────────────

    @override_settings(CADDY_ALLOWED_PARENT_DOMAIN=_PARENT)
    @patch(_PATCH_TARGET)
    def test_existing_tenant_is_allowed(self, mock_get_model):
        mock_get_model.return_value = _mock_domain_model(exists=True)
        result = self.service.evaluate("demo4.api.logsng.tech")
        self.assertIs(result.outcome, result.ALLOW)

    @override_settings(CADDY_ALLOWED_PARENT_DOMAIN=_PARENT)
    @patch(_PATCH_TARGET)
    def test_domain_lookup_uses_lowercase(self, mock_get_model):
        mock_get_model.return_value = _mock_domain_model(exists=True)
        result = self.service.evaluate("DEMO4.Api.Logsng.Tech")
        self.assertIs(result.outcome, result.ALLOW)

    # ── unknown tenant ────────────────────────────────────────────────────────

    @override_settings(CADDY_ALLOWED_PARENT_DOMAIN=_PARENT)
    @patch(_PATCH_TARGET)
    def test_unknown_tenant_is_denied(self, mock_get_model):
        mock_get_model.return_value = _mock_domain_model(exists=False)
        result = self.service.evaluate("ghost.api.logsng.tech")
        self.assertIs(result.outcome, result.DENY)

    # ── empty / missing domain ────────────────────────────────────────────────

    @override_settings(CADDY_ALLOWED_PARENT_DOMAIN=_PARENT)
    def test_empty_string_is_bad_request(self):
        result = self.service.evaluate("")
        self.assertIs(result.outcome, result.BAD_REQUEST)

    @override_settings(CADDY_ALLOWED_PARENT_DOMAIN=_PARENT)
    def test_whitespace_only_is_bad_request(self):
        result = self.service.evaluate("   ")
        self.assertIs(result.outcome, result.BAD_REQUEST)

    # ── IP address rejection ──────────────────────────────────────────────────

    @override_settings(CADDY_ALLOWED_PARENT_DOMAIN=_PARENT)
    def test_ipv4_is_denied(self):
        result = self.service.evaluate("1.2.3.4")
        self.assertIs(result.outcome, result.DENY)

    @override_settings(CADDY_ALLOWED_PARENT_DOMAIN=_PARENT)
    def test_ipv6_is_denied(self):
        result = self.service.evaluate("::1")
        self.assertIs(result.outcome, result.DENY)

    # ── localhost rejection ───────────────────────────────────────────────────

    @override_settings(CADDY_ALLOWED_PARENT_DOMAIN=_PARENT)
    def test_localhost_is_denied(self):
        result = self.service.evaluate("localhost")
        self.assertIs(result.outcome, result.DENY)

    @override_settings(CADDY_ALLOWED_PARENT_DOMAIN=_PARENT)
    def test_subdomain_of_localhost_is_denied(self):
        result = self.service.evaluate("something.localhost")
        self.assertIs(result.outcome, result.DENY)

    # ── wrong parent domain ───────────────────────────────────────────────────

    @override_settings(CADDY_ALLOWED_PARENT_DOMAIN=_PARENT)
    def test_unrelated_domain_is_denied(self):
        result = self.service.evaluate("demo.example.com")
        self.assertIs(result.outcome, result.DENY)

    @override_settings(CADDY_ALLOWED_PARENT_DOMAIN=_PARENT)
    def test_parent_domain_itself_is_denied(self):
        # api.logsng.tech is handled by the named Caddy block, never on-demand.
        result = self.service.evaluate("api.logsng.tech")
        self.assertIs(result.outcome, result.DENY)

    # ── nested subdomain rejection ────────────────────────────────────────────

    @override_settings(CADDY_ALLOWED_PARENT_DOMAIN=_PARENT)
    def test_nested_subdomain_is_denied(self):
        # two.levels.api.logsng.tech — subdomain label is "two.levels" (contains dot)
        result = self.service.evaluate("two.levels.api.logsng.tech")
        self.assertIs(result.outcome, result.DENY)

    # ── malformed subdomain rejection ─────────────────────────────────────────

    @override_settings(CADDY_ALLOWED_PARENT_DOMAIN=_PARENT)
    def test_subdomain_with_underscore_is_denied(self):
        result = self.service.evaluate("bad_name.api.logsng.tech")
        self.assertIs(result.outcome, result.DENY)

    @override_settings(CADDY_ALLOWED_PARENT_DOMAIN=_PARENT)
    def test_subdomain_starting_with_hyphen_is_denied(self):
        result = self.service.evaluate("-bad.api.logsng.tech")
        self.assertIs(result.outcome, result.DENY)

    @override_settings(CADDY_ALLOWED_PARENT_DOMAIN=_PARENT)
    def test_subdomain_ending_with_hyphen_is_denied(self):
        result = self.service.evaluate("bad-.api.logsng.tech")
        self.assertIs(result.outcome, result.DENY)

    # ── valid subdomain formats ───────────────────────────────────────────────

    @override_settings(CADDY_ALLOWED_PARENT_DOMAIN=_PARENT)
    @patch(_PATCH_TARGET)
    def test_single_char_subdomain_is_accepted(self, mock_get_model):
        mock_get_model.return_value = _mock_domain_model(exists=True)
        result = self.service.evaluate("a.api.logsng.tech")
        self.assertIs(result.outcome, result.ALLOW)

    @override_settings(CADDY_ALLOWED_PARENT_DOMAIN=_PARENT)
    @patch(_PATCH_TARGET)
    def test_hyphenated_subdomain_is_accepted(self, mock_get_model):
        mock_get_model.return_value = _mock_domain_model(exists=True)
        result = self.service.evaluate("my-company.api.logsng.tech")
        self.assertIs(result.outcome, result.ALLOW)


class TlsAskViewTests(SimpleTestCase):
    """Integration tests for the tls_ask view via RequestFactory."""

    def setUp(self):
        self.factory = RequestFactory()

    def _get(self, domain: str | None = None):
        params = {} if domain is None else {"domain": domain}
        request = self.factory.get("/internal/tls-ask/", params)
        return tls_ask(request)

    # ── HTTP status codes ─────────────────────────────────────────────────────

    @override_settings(CADDY_ALLOWED_PARENT_DOMAIN=_PARENT)
    @patch(_PATCH_TARGET)
    def test_existing_tenant_returns_200(self, mock_get_model):
        mock_get_model.return_value = _mock_domain_model(exists=True)
        response = self._get("demo4.api.logsng.tech")
        self.assertEqual(response.status_code, 200)

    @override_settings(CADDY_ALLOWED_PARENT_DOMAIN=_PARENT)
    @patch(_PATCH_TARGET)
    def test_unknown_tenant_returns_403(self, mock_get_model):
        mock_get_model.return_value = _mock_domain_model(exists=False)
        response = self._get("ghost.api.logsng.tech")
        self.assertEqual(response.status_code, 403)

    @override_settings(CADDY_ALLOWED_PARENT_DOMAIN=_PARENT)
    def test_empty_domain_returns_400(self):
        response = self._get("")
        self.assertEqual(response.status_code, 400)

    @override_settings(CADDY_ALLOWED_PARENT_DOMAIN=_PARENT)
    def test_missing_domain_param_returns_400(self):
        response = self._get(None)
        self.assertEqual(response.status_code, 400)

    @override_settings(CADDY_ALLOWED_PARENT_DOMAIN=_PARENT)
    def test_invalid_hostname_returns_403(self):
        response = self._get("not-valid.example.com")
        self.assertEqual(response.status_code, 403)

    @override_settings(CADDY_ALLOWED_PARENT_DOMAIN=_PARENT)
    def test_ip_address_returns_403(self):
        response = self._get("10.0.0.1")
        self.assertEqual(response.status_code, 403)

    @override_settings(CADDY_ALLOWED_PARENT_DOMAIN=_PARENT)
    def test_localhost_returns_403(self):
        response = self._get("localhost")
        self.assertEqual(response.status_code, 403)

    # ── response body ─────────────────────────────────────────────────────────

    @override_settings(CADDY_ALLOWED_PARENT_DOMAIN=_PARENT)
    @patch(_PATCH_TARGET)
    def test_200_body_is_ok(self, mock_get_model):
        mock_get_model.return_value = _mock_domain_model(exists=True)
        response = self._get("acme.api.logsng.tech")
        self.assertEqual(response.content, b"ok")

    # ── HTTP method restriction ───────────────────────────────────────────────

    def test_post_returns_405(self):
        request = self.factory.post("/internal/tls-ask/", {"domain": "x.api.logsng.tech"})
        response = tls_ask(request)
        self.assertEqual(response.status_code, 405)
