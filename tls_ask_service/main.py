"""
tls_ask_service — Caddy on-demand TLS callback.

Why this service exists
-----------------------
Caddy's ``on_demand_tls`` feature provisions TLS certificates on the first
HTTPS connection to an unknown hostname.  Before initiating the ACME flow it
calls the ``ask`` URL configured in the global Caddy block::

    on_demand_tls {
        ask http://tls_ask_service:8000/internal/tls-ask/
    }

Caddy passes the requested hostname as ``?domain=``.  It interprets the
response as follows:

    HTTP 2xx  → hostname is permitted; proceed with ACME certificate issuance
    anything else → hostname is NOT permitted; abort TLS handshake

Why this is a separate service and NOT Django
----------------------------------------------
Django runs behind django-tenants, whose ``TenantMainMiddleware`` resolves the
URL conf from the ``Host`` header.  Caddy's ask callback carries::

    Host: tls_ask_service:8000   (the Docker service name)

That host matches no tenant domain and no known schema.  While
``SHOW_PUBLIC_IF_NO_TENANT_FOUND = True`` should fall back to the public URL
conf, ``SECURE_SSL_REDIRECT = True`` in production causes Django's
``SecurityMiddleware`` to return 301 before the view runs — because the ask
arrives over plain HTTP on the Docker internal network.

A dedicated lightweight service sidesteps all of this:
  * No Django middleware stack to navigate
  * No schema routing complexity
  * Starts in < 1 s, uses ~20 MB RAM
  * Queries the same PostgreSQL database Django uses

How new tenants get SSL automatically
---------------------------------------
1. Customer onboards at https://logsng.tech/onboarding
2. Django creates a Client row (tenant) and a Domain row::

       domain = "apo.api.logsng.tech"

3. Customer visits https://apo.api.logsng.tech for the first time
4. Caddy calls GET /internal/tls-ask/?domain=apo.api.logsng.tech
5. This service queries PostgreSQL — the domain row exists → HTTP 200
6. Caddy proceeds to obtain a Let's Encrypt certificate via ACME HTTP-01
7. Certificate is issued; the request is reverse-proxied to Django
8. django-tenants resolves apo.api.logsng.tech → tenant schema "apo"

No manual Caddyfile edits needed for each new tenant.

Environment variables
---------------------
DB_HOST            PostgreSQL host  (default: postgres_db)
DB_PORT            PostgreSQL port  (default: 5432)
DB_NAME            Database name
DB_USER            Database user
DB_PASSWORD        Database password
ALLOWED_PARENT_DOMAIN  Only subdomains of this domain may receive certs
                       (default: api.logsng.tech)
"""

from __future__ import annotations

import ipaddress
import logging
import os
import re
from contextlib import asynccontextmanager

import asyncpg
from fastapi import Depends, FastAPI, Query
from fastapi.responses import PlainTextResponse

# ── logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("tls_ask_service")

# ── validation ────────────────────────────────────────────────────────────────

# RFC-1123 hostname label: 1–63 chars, starts/ends with alnum, hyphens allowed
# inside.  Used to validate the subdomain portion only.
_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?$")

_LOCAL_NAMES = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})


def _allowed_parent_domain() -> str:
    return os.getenv("ALLOWED_PARENT_DOMAIN", "api.logsng.tech").lower().strip()


def _validate_domain(domain: str) -> tuple[bool, str]:
    """
    Validate *domain* before querying the database.

    Returns ``(True, "")`` if the domain passes all checks, or
    ``(False, reason)`` if it should be rejected.
    """
    if not domain or not domain.strip():
        return False, "domain parameter is required"

    domain = domain.lower().strip()

    # Reject IP addresses (IPv4 and IPv6)
    try:
        ipaddress.ip_address(domain)
        return False, "IP addresses are not permitted"
    except ValueError:
        pass

    # Reject localhost variants
    if domain in _LOCAL_NAMES or domain.endswith(".localhost"):
        return False, "localhost is not permitted"

    parent = _allowed_parent_domain()
    required_suffix = f".{parent}"

    # Must be a direct child of the allowed parent domain
    if not domain.endswith(required_suffix):
        return False, f"domain is not under {parent}"

    subdomain = domain[: -len(required_suffix)]

    # The subdomain must be a single, well-formed DNS label (no nested dots)
    if not subdomain:
        return False, "subdomain label is empty"

    if "." in subdomain:
        return False, "nested subdomains are not permitted"

    if not _LABEL_RE.match(subdomain):
        return False, "subdomain contains invalid characters"

    return True, ""


# ── database pool ─────────────────────────────────────────────────────────────

_pool: asyncpg.Pool | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pool
    _pool = await asyncpg.create_pool(
        host=os.getenv("DB_HOST", "postgres_db"),
        port=int(os.getenv("DB_PORT", "5432")),
        database=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        min_size=1,
        max_size=3,
        command_timeout=5,
    )
    logger.info("Database connection pool ready")
    yield
    if _pool:
        await _pool.close()
        logger.info("Database connection pool closed")


async def get_pool() -> asyncpg.Pool:
    return _pool


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="TLS Ask Service",
    description="Caddy on-demand TLS callback for LogsInventory multi-tenant SaaS.",
    version="1.0.0",
    lifespan=lifespan,
    # Hide docs in production if desired:
    # docs_url=None, redoc_url=None,
)


# ── endpoints ─────────────────────────────────────────────────────────────────


@app.get(
    "/internal/tls-ask/",
    response_class=PlainTextResponse,
    summary="Caddy on-demand TLS ask callback",
    responses={
        200: {"description": "Domain is permitted; Caddy may issue the cert"},
        400: {"description": "Request is malformed (missing or empty domain)"},
        403: {"description": "Domain is not permitted; Caddy must NOT issue a cert"},
    },
)
async def tls_ask(
    domain: str = Query(default="", description="Hostname Caddy wants to certify"),
    pool: asyncpg.Pool = Depends(get_pool),
) -> PlainTextResponse:
    """
    Called by Caddy before provisioning a TLS certificate.

    Returns 200 if the domain belongs to a provisioned tenant, 403 otherwise.
    Never returns 404 — a 404 makes the missing-endpoint bug indistinguishable
    from a legitimate denial during debugging.
    """
    raw = domain.strip()

    valid, reason = _validate_domain(raw)
    if not valid:
        # 400 for structurally bad requests, 403 for policy rejections
        if "required" in reason:
            logger.warning("TLS ASK | domain=%r | decision=BAD_REQUEST | %s", raw, reason)
            return PlainTextResponse(reason, status_code=400)
        logger.warning("TLS ASK | domain=%r | decision=DENY | %s", raw or "(empty)", reason)
        return PlainTextResponse(reason, status_code=403)

    # Normalise to lowercase (already done in _validate_domain, re-apply here
    # to use the cleansed value for the DB query)
    normalized = raw.lower().strip()

    # The django-tenants Domain table lives in the public schema.
    # Table name: <app_label>_<model_name> → clients_domain
    exists: bool = await pool.fetchval(
        "SELECT EXISTS(SELECT 1 FROM clients_domain WHERE domain = $1)",
        normalized,
    )

    if exists:
        logger.info("TLS ASK | domain=%r | decision=ALLOW | tenant domain found", normalized)
        return PlainTextResponse("ok", status_code=200)

    logger.warning(
        "TLS ASK | domain=%r | decision=DENY | no tenant domain found", normalized
    )
    return PlainTextResponse("domain not found", status_code=403)


@app.get("/health", response_class=PlainTextResponse, include_in_schema=False)
async def health(pool: asyncpg.Pool = Depends(get_pool)) -> PlainTextResponse:
    """Liveness probe used by Docker Compose healthcheck."""
    try:
        await pool.fetchval("SELECT 1")
        return PlainTextResponse("ok", status_code=200)
    except Exception as exc:
        logger.error("Health check failed: %s", exc)
        return PlainTextResponse("unhealthy", status_code=503)
