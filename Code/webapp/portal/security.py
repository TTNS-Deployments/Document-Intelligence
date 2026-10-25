"""Health check and security headers (no extra package needed)."""

from django.conf import settings
from django.http import HttpResponse


class HealthCheckMiddleware:
    """Answers ``/healthz`` first, so App Service probes never depend on host names, HTTPS redirects or sign-in."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == "/healthz":
            return HttpResponse("ok", content_type="text/plain")
        return self.get_response(request)


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if settings.CONTENT_SECURITY_POLICY and "Content-Security-Policy" not in response:
            response["Content-Security-Policy"] = settings.CONTENT_SECURITY_POLICY
        response.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if request.path.startswith(("/api/", "/documents/", "/partials/")):
            response.setdefault("Cache-Control", "no-store")  # document data is sensitive
        return response


class StartJobsMiddleware:
    """Starts the analysis worker threads on the first request after a start, which also re-queues jobs left
    behind by a restart (docintel.jobs.recover). Later requests cost one attribute check."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.started = False

    def __call__(self, request):
        if not self.started:
            self.started = True
            from docintel.factory import get_job_runner

            get_job_runner().ensure_started()
        return self.get_response(request)
