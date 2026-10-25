import hmac
import logging
import secrets

from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from .roles import ROLES, USER, User

log = logging.getLogger(__name__)


def _safe_next(request, url: str | None) -> str:
    if url and url_has_allowed_host_and_scheme(url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return url
    return reverse("portal:extract")


def client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")  # App Service front end: "client:port, proxy"
    first = forwarded.split(",")[0].strip() if forwarded else ""
    if first.count(":") == 1:  # IPv4 with a port
        first = first.split(":")[0]
    return first or request.META.get("REMOTE_ADDR", "")


@require_http_methods(["GET", "POST"])
def login(request):
    next_url = request.GET.get("next") or request.POST.get("next") or ""
    mode = settings.AUTH_MODE
    configured = mode == "dev" or bool(settings.DEMO_PASSWORD)
    context = {"mode": mode, "next": next_url, "configured": configured, "roles": ROLES,
               "selected_role": request.POST.get("role", USER)}
    if request.method == "GET" or not configured:
        if request.user.is_authenticated and request.method == "GET":
            return redirect(_safe_next(request, next_url))
        return render(request, "accounts/login.html", context)

    role = request.POST.get("role", "")
    if role not in ROLES:
        messages.error(request, "Choose Admin or User.")
        return render(request, "accounts/login.html", context, status=400)

    if mode == "password":
        key = f"login-failures:{client_ip(request)}"
        failures = cache.get(key, 0)
        if failures >= settings.LOGIN_MAX_FAILURES:
            messages.error(request, "Too many wrong passwords from this address. Try again in 15 minutes.")
            context["locked"] = True
            return render(request, "accounts/login.html", context, status=429)
        given = request.POST.get("password", "")
        if not hmac.compare_digest(given.encode(), settings.DEMO_PASSWORD.encode()):
            cache.set(key, failures + 1, settings.LOGIN_LOCK_SECONDS)
            left = settings.LOGIN_MAX_FAILURES - failures - 1
            log.warning("Wrong demo password (%d of %d)", failures + 1, settings.LOGIN_MAX_FAILURES)
            messages.error(request, "Wrong password." + (f" {left} attempt{'s' if left != 1 else ''} left before "
                                                         "sign-in is paused for 15 minutes." if left <= 2 else ""))
            return render(request, "accounts/login.html", context, status=403)
        cache.delete(key)

    request.session.cycle_key()
    request.session["user"] = User(id=secrets.token_hex(8), role=role).to_session()
    log.info("Signed in as %s", role)
    return redirect(_safe_next(request, next_url))


@require_POST
def logout(request):
    request.session.flush()
    return redirect("accounts:login")
