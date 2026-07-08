"""
Caddy on-demand TLS validation service.

Why Caddy calls this endpoint
------------------------------
Caddy's ``on_demand_tls`` feature provisions TLS certificates at the moment of
the first HTTPS connection for a hostname it has not seen before, instead of at
startup.  Before initiating the ACME certificate flow with Let's Encrypt, Caddy
calls the ``ask`` URL configured in the global block:

    on_demand_tls {
        ask http://inventory_backend_app:8400/internal/tls-ask/
    }

Caddy sends a GET request with the requested hostname as ``?domain=``.  It
interprets the HTTP response status as follows:

    HTTP 2xx  → hostname is permitted; proceed with ACME certificate issuance
    anything else → hostname is NOT permitted; abort the TLS handshake

Why a 404 breaks on-demand TLS
--------------------------------
If this endpoint returns 404 (because it isn't registered, or the URL conf is
wrong), Caddy treats the domain as rejected—non-2xx is non-2xx—and closes the
TLS handshake before a certificate is ever issued.  The browser receives
``ERR_SSL_PROTOCOL_ERROR`` because the SSL handshake never completed.

Why 403 is the correct rejection status
-----------------------------------------
403 Forbidden communicates a deliberate policy decision: "I received and
understood the request, and I am refusing it."  This is semantically correct
for an unknown subdomain and makes debugging straightforward—you can tell at a
glance whether the endpoint is missing (404) or is working but rejecting the
domain (403).

How new tenants receive SSL automatically
------------------------------------------
The onboarding flow creates a ``Client`` (tenant) and a ``Domain`` row in the
database.  The next time a browser connects to that subdomain over HTTPS, Caddy
calls this endpoint, receives HTTP 200 because the Domain row now exists, and
proceeds to obtain a Let's Encrypt certificate via the ACME HTTP-01 or
TLS-ALPN-01 challenge.  No manual certificate management is needed—every new
workspace gets HTTPS automatically within seconds of its first request.
"""

from __future__ import annotations

import ipaddress
import logging
import re
from dataclasses import dataclass
from enum import Enum, auto

from django.conf import settings
from django_tenants.utils import get_tenant_domain_model

logger = logging.getLogger("inventory_logs.caddy")

# RFC-1123 hostname label: starts/ends with alnum, may contain hyphens, 1–63 chars.
_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?$")


class _Outcome(Enum):
    ALLOW = auto()
    DENY = auto()
    BAD_REQUEST = auto()


@dataclass(frozen=True)
class TlsAskResult:
    outcome: _Outcome
    reason: str

    # Expose constants so callers can compare without importing _Outcome.
    ALLOW = _Outcome.ALLOW
    DENY = _Outcome.DENY
    BAD_REQUEST = _Outcome.BAD_REQUEST


class CaddyTlsAskService:
    """
    Validates whether Caddy should be allowed to provision a TLS certificate
    for the requested hostname.

    All settings are read on each call so that ``override_settings`` works
    correctly in tests and so that a running server picks up config changes
    without a restart (when the settings module is reloaded).
    """

    def evaluate(self, raw_domain: str) -> TlsAskResult:
        """
        Evaluate whether *raw_domain* should receive a TLS certificate.

        Returns a :class:`TlsAskResult` whose ``outcome`` is one of:

        * ``TlsAskResult.ALLOW``       — HTTP 200; Caddy may issue the cert
        * ``TlsAskResult.DENY``        — HTTP 403; Caddy must not issue the cert
        * ``TlsAskResult.BAD_REQUEST`` — HTTP 400; request is malformed
        """
        parent_domain: str = getattr(
            settings, "CADDY_ALLOWED_PARENT_DOMAIN", settings.BASE_DOMAIN
        ).lower().strip()

        # ── 1. Presence ───────────────────────────────────────────────────────
        if not raw_domain or not raw_domain.strip():
            return TlsAskResult(
                _Outcome.BAD_REQUEST, "domain query parameter is required"
            )

        domain = raw_domain.lower().strip()

        # ── 2. Reject IP addresses ────────────────────────────────────────────
        # ipaddress.ip_address() accepts both IPv4 and IPv6; ValueError means it
        # is not an IP, which is what we want for hostname input.
        try:
            ipaddress.ip_address(domain)
            return TlsAskResult(_Outcome.DENY, "IP addresses are not permitted")
        except ValueError:
            pass

        # ── 3. Reject localhost variants ──────────────────────────────────────
        _LOCAL = {"localhost", "127.0.0.1", "::1", "[::1]"}
        if domain in _LOCAL or domain.endswith(".localhost"):
            return TlsAskResult(_Outcome.DENY, "localhost is not permitted")

        # ── 4. Require exactly one subdomain level under the parent domain ────
        # e.g. with parent "api.logsng.tech":
        #   allowed prefix pattern: "demo4.api.logsng.tech"
        #   rejected:               "api.logsng.tech"  (is the parent itself)
        #   rejected:               "a.b.api.logsng.tech" (two levels deep)
        required_suffix = f".{parent_domain}"
        if not domain.endswith(required_suffix):
            return TlsAskResult(
                _Outcome.DENY,
                f"domain is not a direct subdomain of {parent_domain}",
            )

        subdomain = domain[: -len(required_suffix)]

        # ── 5. Validate the subdomain label ───────────────────────────────────
        if not subdomain:
            return TlsAskResult(_Outcome.DENY, "subdomain label is empty")

        if "." in subdomain:
            return TlsAskResult(
                _Outcome.DENY, "nested subdomains are not permitted"
            )

        if not _LABEL_RE.match(subdomain):
            return TlsAskResult(
                _Outcome.DENY,
                "subdomain contains invalid characters or format",
            )

        # ── 6. Database lookup ────────────────────────────────────────────────
        # Use get_tenant_domain_model() so this works even if the project
        # has overridden TENANT_DOMAIN_MODEL in settings.
        DomainModel = get_tenant_domain_model()
        if DomainModel.objects.filter(domain=domain).exists():
            return TlsAskResult(_Outcome.ALLOW, "tenant domain exists")

        return TlsAskResult(
            _Outcome.DENY, f"no tenant found for domain '{domain}'"
        )
