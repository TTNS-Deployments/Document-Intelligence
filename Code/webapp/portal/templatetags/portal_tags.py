from datetime import datetime

from django import template
from django.utils import timezone

register = template.Library()


@register.filter
def percent(value):
    """0.873 -> "87%"."""
    if value is None or value == "":
        return "–"
    return f"{round(float(value) * 100)}%"


@register.filter
def conf_width(value):
    """CSS width for a confidence bar."""
    return 0 if value is None else max(2, min(100, round(float(value) * 100)))


@register.filter
def conf_level(value, threshold=0.8):
    if value is None:
        return "none"
    value, threshold = float(value), float(threshold)
    if value < threshold:
        return "low"
    return "high" if value >= max(0.9, threshold) else "ok"


@register.filter
def localtime_iso(value):
    """An ISO timestamp string as a local, aware datetime (DISPLAY_TIME_ZONE)."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.utc)
    return timezone.localtime(dt)


@register.filter
def duration(ms):
    if ms in (None, ""):
        return "–"
    seconds = int(ms) / 1000
    return f"{seconds:.1f} s" if seconds < 60 else f"{int(seconds // 60)} min {int(seconds % 60)} s"


@register.filter
def filesize(n):
    n = int(n or 0)
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n / 1048576:.1f} MB"


@register.filter
def get_item(mapping, key):
    return mapping.get(key) if hasattr(mapping, "get") else None


@register.simple_tag
def status_label(status):
    return {"queued": "Queued", "processing": "Processing", "done": "Done", "failed": "Failed"}.get(status, status)


@register.filter
def to_json(value):
    """JSON for a data attribute (Django escapes the quotes; the browser decodes them)."""
    import json

    return json.dumps(value, separators=(",", ":"))


@register.filter
def picture_regions(figure):
    """A picture's box in the same shape as field regions, so the preview draws and links it."""
    return [{"page": figure.get("page", 1), "polygon": figure.get("polygon") or []}] if figure.get("polygon") else []
