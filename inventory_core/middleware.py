class SkipSSLRedirectForInternalCaddy:
    """
    Caddy calls /internal/tls-ask/ over HTTP inside Docker.
    This marks that internal request as HTTPS so Django SecurityMiddleware
    does not redirect it.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == "/internal/tls-ask/":
            request.META["HTTP_X_FORWARDED_PROTO"] = "https"

        return self.get_response(request)
