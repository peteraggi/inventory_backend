"""
Tests for the tls_ask_service FastAPI application.

Strategy
--------
* The database dependency (``get_pool``) is overridden with a mock via
  FastAPI's ``app.dependency_overrides`` before each test class/fixture.
* ``TestClient`` is used **without** a context manager so the lifespan
  (``asynccontextmanager``) — which connects to PostgreSQL — never runs.
  Individual requests work through FastAPI's ASGI transport without needing
  startup to complete.
* ``monkeypatch.setenv`` controls ``ALLOWED_PARENT_DOMAIN`` per test.
* The mock pool's ``fetchval`` method is replaced with ``AsyncMock`` so the
  endpoint's ``await pool.fetchval(...)`` call resolves without hitting the DB.

Running
-------
From inside the ``tls_ask_service/`` directory:

    pip install -r requirements.txt pytest pytest-asyncio httpx
    pytest tests/ -v
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from main import app, get_pool

_PARENT = "api.logsng.tech"


# ── fixtures ──────────────────────────────────────────────────────────────────


def _make_pool(*, domain_exists: bool) -> AsyncMock:
    """Return a mock asyncpg pool whose fetchval() returns *domain_exists*."""
    pool = AsyncMock()
    pool.fetchval = AsyncMock(return_value=domain_exists)
    return pool


@pytest.fixture
def allow(monkeypatch):
    """TestClient where any domain is found in the database."""
    monkeypatch.setenv("ALLOWED_PARENT_DOMAIN", _PARENT)
    mock_pool = _make_pool(domain_exists=True)
    app.dependency_overrides[get_pool] = lambda: mock_pool
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def deny(monkeypatch):
    """TestClient where no domain is found in the database."""
    monkeypatch.setenv("ALLOWED_PARENT_DOMAIN", _PARENT)
    mock_pool = _make_pool(domain_exists=False)
    app.dependency_overrides[get_pool] = lambda: mock_pool
    yield TestClient(app)
    app.dependency_overrides.clear()


# ── helper ────────────────────────────────────────────────────────────────────


def ask(client: TestClient, domain: str | None = None) -> ...:
    params = {} if domain is None else {"domain": domain}
    return client.get("/internal/tls-ask/", params=params)


# ── happy path ────────────────────────────────────────────────────────────────


class TestAllow:
    def test_existing_tenant_returns_200(self, allow):
        r = ask(allow, "demo4.api.logsng.tech")
        assert r.status_code == 200
        assert r.text == "ok"

    def test_response_is_plain_text(self, allow):
        r = ask(allow, "demo4.api.logsng.tech")
        assert "text/plain" in r.headers["content-type"]

    def test_uppercase_domain_is_normalised(self, allow):
        """Domain matching must be case-insensitive."""
        r = ask(allow, "DEMO4.API.LOGSNG.TECH")
        assert r.status_code == 200

    def test_single_char_subdomain(self, allow):
        r = ask(allow, "a.api.logsng.tech")
        assert r.status_code == 200

    def test_hyphenated_subdomain(self, allow):
        r = ask(allow, "my-company.api.logsng.tech")
        assert r.status_code == 200


# ── domain not in database ────────────────────────────────────────────────────


class TestDeny:
    def test_unknown_tenant_returns_403(self, deny):
        r = ask(deny, "ghost.api.logsng.tech")
        assert r.status_code == 403

    def test_403_body_is_informative(self, deny):
        r = ask(deny, "ghost.api.logsng.tech")
        assert r.status_code == 403
        assert r.text  # non-empty body


# ── missing / empty domain ────────────────────────────────────────────────────


class TestBadRequest:
    def test_missing_domain_param_returns_400(self, deny):
        r = ask(deny, None)
        assert r.status_code == 400

    def test_empty_string_returns_400(self, deny):
        r = ask(deny, "")
        assert r.status_code == 400

    def test_whitespace_only_returns_400(self, deny):
        r = ask(deny, "   ")
        assert r.status_code == 400


# ── IP address rejection ──────────────────────────────────────────────────────


class TestIpAddresses:
    def test_ipv4_returns_403(self, deny):
        r = ask(deny, "1.2.3.4")
        assert r.status_code == 403

    def test_ipv6_returns_403(self, deny):
        r = ask(deny, "::1")
        assert r.status_code == 403

    def test_private_ipv4_returns_403(self, deny):
        r = ask(deny, "192.168.1.1")
        assert r.status_code == 403


# ── localhost rejection ───────────────────────────────────────────────────────


class TestLocalhost:
    def test_localhost_returns_403(self, deny):
        r = ask(deny, "localhost")
        assert r.status_code == 403

    def test_subdomain_of_localhost_returns_403(self, deny):
        r = ask(deny, "app.localhost")
        assert r.status_code == 403

    def test_loopback_ip_returns_403(self, deny):
        r = ask(deny, "127.0.0.1")
        assert r.status_code == 403


# ── wrong parent domain ───────────────────────────────────────────────────────


class TestWrongParent:
    def test_external_domain_returns_403(self, deny):
        r = ask(deny, "google.com")
        assert r.status_code == 403

    def test_unrelated_subdomain_returns_403(self, deny):
        r = ask(deny, "demo.example.com")
        assert r.status_code == 403

    def test_parent_domain_itself_returns_403(self, deny):
        # api.logsng.tech is handled by the named Caddy block; on_demand
        # should never be called for it, but if it is, reject it.
        r = ask(deny, "api.logsng.tech")
        assert r.status_code == 403

    def test_look_alike_suffix_returns_403(self, deny):
        # "evil-api.logsng.tech" ends with "logsng.tech" but not ".api.logsng.tech"
        r = ask(deny, "evil-api.logsng.tech")
        assert r.status_code == 403


# ── nested / malformed subdomain rejection ────────────────────────────────────


class TestMalformed:
    def test_nested_subdomain_returns_403(self, deny):
        r = ask(deny, "a.b.api.logsng.tech")
        assert r.status_code == 403

    def test_subdomain_with_underscore_returns_403(self, deny):
        r = ask(deny, "bad_name.api.logsng.tech")
        assert r.status_code == 403

    def test_subdomain_leading_hyphen_returns_403(self, deny):
        r = ask(deny, "-bad.api.logsng.tech")
        assert r.status_code == 403

    def test_subdomain_trailing_hyphen_returns_403(self, deny):
        r = ask(deny, "bad-.api.logsng.tech")
        assert r.status_code == 403


# ── HTTP method ───────────────────────────────────────────────────────────────


class TestHttpMethod:
    def test_post_returns_405(self, deny):
        r = deny.post("/internal/tls-ask/", params={"domain": "demo4.api.logsng.tech"})
        assert r.status_code == 405


# ── health check ──────────────────────────────────────────────────────────────


class TestHealth:
    def test_health_returns_200(self, allow):
        # The health endpoint also uses get_pool; mock returns 1 from fetchval
        r = allow.get("/health")
        assert r.status_code == 200
        assert r.text == "ok"
