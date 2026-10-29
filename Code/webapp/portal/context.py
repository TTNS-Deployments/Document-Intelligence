from django.conf import settings
from django.urls import reverse

NAV = [
    ("extract", "Extract", "portal:extract", "extract"),
    ("batches", "Batches", "portal:batches", "extract"),
    ("history", "History", "portal:history", "extract"),
    ("settings", "Settings", "portal:settings", "manage_settings"),
]


def portal(request):
    user = getattr(request, "user", None)
    items = []
    if user is not None and user.is_authenticated:
        items = [{"key": key, "label": label, "href": reverse(name)} for key, label, name, perm in NAV if user.can(perm)]
    match = getattr(request, "resolver_match", None)
    active = {"document": "history", "batch": "batches"}.get(match.url_name, match.url_name) if match else ""
    return {"nav_items": items, "active_nav": active, "docintel_mode": settings.DOCINTEL_MODE,
            "auth_mode": settings.AUTH_MODE, "environment_name": settings.ENVIRONMENT_NAME,
            "app_version": settings.APP_VERSION}
