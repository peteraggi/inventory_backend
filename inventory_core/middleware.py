class SkipSSLRedirectForInternalCaddy:
    """
    Exempt /internal/* from Django's SECURE_SSL_REDIRECT.

    Caddy's on_demand_tls ``ask`` callback arrives over plain HTTP on the
    internal Docker network:

        GET http://inventory_backend_app:8400/internal/tls-ask/?domain=...

    With SECURE_SSL_REDIRECT=True, Django's SecurityMiddleware returns 301.
    Caddy treats any non-2xx as "domain not permitted" and aborts the TLS
    handshake — the browser gets ERR_SSL_PROTOCOL_ERROR.

    This middleware runs before SecurityMiddleware and marks /internal/*
    requests as already-HTTPS so the redirect is skipped.  The path prefix
    is never exposed to the public internet; it is only reachable from other
    containers on the inventory_network Docker bridge.

    Middleware order (settings.py):
        TenantMainMiddleware
        SkipSSLRedirectForInternalCaddy   ← must be before SecurityMiddleware
        SecurityMiddleware
        ...
    """

    _INTERNAL_PREFIX = "/internal/"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path_info.startswith(self._INTERNAL_PREFIX):
            # SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
            # Setting this header makes request.is_secure() return True,
            # which stops SecurityMiddleware from issuing the redirect.
            request.META["HTTP_X_FORWARDED_PROTO"] = "https"
        return self.get_response(request)
