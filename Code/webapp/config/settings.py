"""Django settings for the Document Intelligence web app.

All settings come from environment variables (App Service app settings in Azure). Storage, Document Intelligence
and limits are read by ``docintel.config``.
"""

import mimetypes
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
mimetypes.add_type("text/javascript", ".mjs")  # pdf.js modules


def env(name, default=""):
    value = os.environ.get(name, default).strip()
    # An unresolved App Service Key Vault reference arrives as the literal reference string.
    return "" if value.startswith("@Microsoft.KeyVault(") else value


def env_bool(name, default=False):
    value = env(name)
    return default if not value else value.lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [v.strip() for v in env(name, default).split(",") if v.strip()]


def env_int(name, default):
    value = env(name, str(default))
    try:
        return int(value)
    except ValueError:
        raise RuntimeError(f"{name} must be a whole number, got {value!r}") from None


DOCINTEL_MODE = env("DOCINTEL_MODE", "local").lower()
if DOCINTEL_MODE not in {"local", "azure"}:
    raise RuntimeError(f"Unknown DOCINTEL_MODE {DOCINTEL_MODE!r} (local or azure)")
IS_LOCAL = DOCINTEL_MODE == "local"
ENVIRONMENT_NAME = env("ENVIRONMENT_NAME", "local" if IS_LOCAL else "azure")
APP_VERSION = "1.0.0"

SECRET_KEY = env("DJANGO_SECRET_KEY") or ("local-dev-only-insecure-key" if IS_LOCAL else "")
if not SECRET_KEY and "collectstatic" in sys.argv:  # packaging runs collectstatic without app secrets
    SECRET_KEY = "build-only-not-used-at-runtime"
if not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY must be set outside local mode")

# Off unless asked for, also in local mode, so error pages never show tracebacks or settings by default.
DEBUG = env_bool("DJANGO_DEBUG", False)

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")
if env("WEBSITE_HOSTNAME"):  # set automatically by App Service
    ALLOWED_HOSTS.append(env("WEBSITE_HOSTNAME"))
    CSRF_TRUSTED_ORIGINS.append(f"https://{env('WEBSITE_HOSTNAME')}")

INSTALLED_APPS = [
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "portal",
]

MIDDLEWARE = [
    "portal.security.StartJobsMiddleware",  # starts the job workers (and restart recovery) once
    "portal.security.HealthCheckMiddleware",  # answers /healthz before host checks and redirects
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "accounts.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "portal.security.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {
        "context_processors": [
            "django.template.context_processors.request",
            "django.template.context_processors.csrf",
            "django.contrib.messages.context_processors.messages",
            "portal.context.portal",
        ],
    },
}]

# No relational database: results live in Blob Storage (or a local folder) through the docintel package,
# sessions are signed cookies.
DATABASES = {}
SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
SESSION_COOKIE_AGE = 8 * 3600
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
MESSAGE_STORAGE = "django.contrib.messages.storage.cookie.CookieStorage"
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "docintel"}}

if not IS_LOCAL:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SSL_REDIRECT", True)
    SECURE_REDIRECT_EXEMPT = [r"^healthz$"]
    SECURE_HSTS_SECONDS = 3600
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

LANGUAGE_CODE = "en-gb"
TIME_ZONE = env("DISPLAY_TIME_ZONE", "Asia/Kolkata")
USE_I18N = False
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
# Hashed, compressed files after `collectstatic` (App Service, Docker). Local runs without collectstatic
# (make run) serve the files straight from static/ instead.
_COLLECTED = (STATIC_ROOT / "staticfiles.json").is_file()
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        if not DEBUG and (_COLLECTED or not IS_LOCAL or "collectstatic" in sys.argv)
        else "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}
WHITENOISE_USE_FINDERS = DEBUG or (IS_LOCAL and not _COLLECTED)
WHITENOISE_AUTOREFRESH = WHITENOISE_USE_FINDERS
WHITENOISE_MIMETYPES = {".mjs": "text/javascript"}
# pdf.js loads its worker and fonts by URL: keep those un-hashed copies reachable too.
WHITENOISE_KEEP_ONLY_HASHED_FILES = False

# Uploads: files are checked by docintel.pages (type, magic bytes, size, pages) before anything is stored.
MAX_UPLOAD_MB = env_int("MAX_UPLOAD_MB", 10)
MAX_FILES_PER_UPLOAD = env_int("MAX_FILES_PER_UPLOAD", 10)
FILE_UPLOAD_MAX_MEMORY_SIZE = 2_621_440  # larger files are spooled to a temporary file
DATA_UPLOAD_MAX_MEMORY_SIZE = 1_048_576  # non-file form data
DATA_UPLOAD_MAX_NUMBER_FILES = MAX_FILES_PER_UPLOAD + 1  # one more, so the API can answer with a clear message

# ---- Sign-in ---------------------------------------------------------------------------------
# password : one shared demo password plus an Admin or User choice (demo environments). Sign-in is refused
#            while DEMO_PASSWORD is empty, never open.
# dev      : choose Admin or User without a password (local mode only; refused otherwise)
AUTH_MODE = env("AUTH_MODE", "dev" if IS_LOCAL else "password").lower()
if AUTH_MODE == "dev" and not IS_LOCAL:
    raise RuntimeError("AUTH_MODE=dev is only allowed when DOCINTEL_MODE=local")
if AUTH_MODE not in {"dev", "password"}:
    raise RuntimeError(f"Unknown AUTH_MODE {AUTH_MODE!r} (password or dev)")
DEMO_PASSWORD = env("DEMO_PASSWORD")
LOGIN_MAX_FAILURES = 5  # per client address, then locked
LOGIN_LOCK_SECONDS = 15 * 60

# ---- Content-Security-Policy (portal.security) ----------------------------------------------------
# Scripts come only from this app (libraries are vendored in static/vendor) and there are no inline scripts.
CONTENT_SECURITY_POLICY = env("CONTENT_SECURITY_POLICY") or "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    "worker-src 'self' blob:",
    "connect-src 'self'",
    "frame-ancestors 'none'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
])

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
    "loggers": {"azure": {"level": "WARNING"}, "urllib3": {"level": "WARNING"},
                "django.request": {"level": "ERROR"}, "pypdf": {"level": "ERROR"}},
}

if env("APPLICATIONINSIGHTS_CONNECTION_STRING"):
    try:  # optional: pip install azure-monitor-opentelemetry (not bundled, to keep the package small)
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor()
    except ImportError:
        pass
