from django.http import HttpResponse


class DevelopmentCorsMiddleware:
    """Permit the Flutter web development server to call the local JSON API.

    Deployments should replace ``*`` with the production app origin.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/api/") and request.method == "OPTIONS":
            response = HttpResponse(status=204)
        else:
            response = self.get_response(request)
        if request.path.startswith("/api/"):
            response["Access-Control-Allow-Origin"] = "*"
            response["Access-Control-Allow-Methods"] = "GET, POST, PATCH, OPTIONS"
            response["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-Device-Key"
        return response
