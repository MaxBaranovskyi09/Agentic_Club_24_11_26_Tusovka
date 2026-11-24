from django.conf import settings
from django.http import HttpResponse


class RequestSizeLimitMiddleware:
    """Відхиляє запити з тілом більшим за REQUEST_BODY_MAX_BYTES ще до розбору multipart."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            length = int(request.META.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = 0
        if length > settings.REQUEST_BODY_MAX_BYTES:
            return HttpResponse(
                "Запит завеликий.", status=413, content_type="text/plain; charset=utf-8"
            )
        return self.get_response(request)
