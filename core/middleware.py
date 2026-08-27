import re

from django.conf import settings
from django.http import HttpResponse
from django.utils.cache import patch_vary_headers


class DevelopmentCorsMiddleware:
    """Allow configured Flutter web origins while keeping native clients working."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/api/") and request.method == "OPTIONS":
            response = HttpResponse(status=204)
        else:
            response = self.get_response(request)
        if request.path.startswith("/api/"):
            origin = request.headers.get("Origin", "")
            origin_matches_pattern = origin and any(
                re.fullmatch(pattern, origin)
                for pattern in settings.CORS_ALLOWED_ORIGIN_REGEXES
            )
            if settings.DEBUG and origin:
                response["Access-Control-Allow-Origin"] = origin
            elif origin in settings.CORS_ALLOWED_ORIGINS or origin_matches_pattern:
                response["Access-Control-Allow-Origin"] = origin
            if origin:
                patch_vary_headers(response, ("Origin",))
            response["Access-Control-Allow-Methods"] = "GET, POST, PATCH, OPTIONS"
            response["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-Device-Key"
        return response
