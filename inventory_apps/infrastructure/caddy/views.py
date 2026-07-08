import logging

from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.views.decorators.http import require_GET

from .services import CaddyTlsAskService, TlsAskResult

logger = logging.getLogger("inventory_logs.caddy")

_service = CaddyTlsAskService()


@require_GET
def tls_ask(request: HttpRequest) -> HttpResponse:
    """
    GET /internal/tls-ask/?domain=<hostname>

    Caddy's on_demand_tls ``ask`` callback.  Called before Caddy provisions a
    TLS certificate for any hostname served by the ``https://`` catch-all site
    block.  Returns:

    * 200 — hostname belongs to a provisioned tenant; Caddy may issue the cert
    * 400 — request is malformed (missing domain parameter)
    * 403 — hostname is not permitted; Caddy must NOT issue the cert

    Never returns 404: a 404 from this endpoint causes Caddy to treat the domain
    as rejected AND makes the missing-endpoint bug indistinguishable from a
    legitimate denial during debugging.
    """
    raw_domain = request.GET.get("domain", "")
    result = _service.evaluate(raw_domain)

    if result.outcome is TlsAskResult.ALLOW:
        logger.info(
            "TLS ASK | domain=%r | decision=ALLOW | reason=%s",
            raw_domain,
            result.reason,
        )
        return HttpResponse("ok", content_type="text/plain")

    if result.outcome is TlsAskResult.BAD_REQUEST:
        logger.warning(
            "TLS ASK | domain=%r | decision=BAD_REQUEST | reason=%s",
            raw_domain,
            result.reason,
        )
        return HttpResponseBadRequest(result.reason, content_type="text/plain")

    # DENY
    logger.warning(
        "TLS ASK | domain=%r | decision=DENY | reason=%s",
        raw_domain,
        result.reason,
    )
    return HttpResponseForbidden(result.reason, content_type="text/plain")
