from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse

from .roles import AnonymousUser, User

PUBLIC_PREFIXES = ("/auth/", "/static/", "/healthz")


class AuthenticationMiddleware:
    """Puts ``request.user`` on every request. Anonymous users are sent to sign in (API calls get 401)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = User.from_session(request.session.get("user")) if "user" in request.session else None
        request.user = user or AnonymousUser()
        if not request.user.is_authenticated and not request.path.startswith(PUBLIC_PREFIXES):
            if request.path.startswith("/api/") or request.headers.get("HX-Request"):
                response = JsonResponse({"error": "Sign in first."}, status=401)
                response["HX-Redirect"] = reverse("accounts:login")
                return response
            return redirect(f"{reverse('accounts:login')}?next={request.get_full_path()}")
        return self.get_response(request)
