import datetime
import os
from pathlib import Path
from decouple import config

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config("DJANGO_SECRET_KEY")
DEBUG = config("DEBUG", default=False, cast=bool)

AUTH_USER_MODEL = "authentication.User"

# Base domain tenants are provisioned under, e.g. {subdomain}.api.logsng.tech
BASE_DOMAIN = config("BASE_DOMAIN", default="api.logsng.tech")

# Parent domain the Caddy tls-ask endpoint uses to validate tenant subdomains.
# Caddy will only be allowed to provision certs for <subdomain>.<CADDY_ALLOWED_PARENT_DOMAIN>.
# Defaults to BASE_DOMAIN, so no extra env var is needed in the common case.
CADDY_ALLOWED_PARENT_DOMAIN = config("CADDY_ALLOWED_PARENT_DOMAIN", default=BASE_DOMAIN)

# django-tenants: wildcard allows *.api.logsng.tech and the root domain
ALLOWED_HOSTS = [
    BASE_DOMAIN,
    f".{BASE_DOMAIN}",  # wildcard for all tenant subdomains
    "localhost",
    ".localhost",
    "127.0.0.1",
    "inventory_backend_app",  # Caddy's on_demand_tls "ask" callback hits this internal name
]

# ─── Multi-tenancy ────────────────────────────────────────────────────────────
TENANT_MODEL = "clients.Client"
TENANT_DOMAIN_MODEL = "clients.Domain"
PUBLIC_SCHEMA_URLCONF = "inventory_core.urls_public"
SHOW_PUBLIC_IF_NO_TENANT_FOUND = True

# Shared apps live in the public (shared) PostgreSQL schema
SHARED_APPS = [
    "django_tenants",  # must be first
    "inventory_apps.clients",  # Client, Domain, SubscriptionPlan
    "inventory_apps.pos_app",
    "inventory_apps.authentication",  # ← move here, BEFORE admin
    "rest_framework_simplejwt.token_blacklist",  # blacklist references User too
    "django.contrib.contenttypes",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "drf_yasg",
    "django_celery_results",
    "django_celery_beat",
    "django_filters",
]

# Tenant apps are migrated into every tenant's individual schema
TENANT_APPS = [
    # 'rest_framework_simplejwt.token_blacklist',
    # 'inventory_apps.authentication',
    "inventory_apps.pos_app",
]

# INSTALLED_APPS must be SHARED_APPS ∪ TENANT_APPS (shared first, no duplicates)
INSTALLED_APPS = list(SHARED_APPS) + [
    app for app in TENANT_APPS if app not in SHARED_APPS
]

SWAGGER_SETTINGS = {
    "USE_SESSION_AUTH": False,
    "SECURITY_DEFINITIONS": {
        "Bearer": {"type": "apiKey", "name": "Authorization", "in": "header"}
    },
}

MIDDLEWARE = [
    # TenantMainMiddleware MUST be first — reads subdomain, sets schema
    "django_tenants.middleware.main.TenantMainMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "inventory_core.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "inventory_core.wsgi.application"


# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases

DATABASES = {
    "default": {
        # django-tenants requires the postgresql_psycopg2 backend
        "ENGINE": "django_tenants.postgresql_backend",
        "NAME": config("POSTGRES_DB"),
        "USER": config("POSTGRES_USER"),
        "PASSWORD": config("POSTGRES_PASSWORD"),
        "HOST": config("PG_HOST", default="postgres_db"),
        "PORT": config("PG_PORT", default="5432"),
    }
}

DATABASE_ROUTERS = ("django_tenants.routers.TenantSyncRouter",)

CELERY_BROKER_URL = f"redis://:{config('REDIS_PASSWORD')}@redis:6379/0"
CELERY_RESULT_BACKEND = f"redis://:{config('REDIS_PASSWORD')}@redis:6379/2"
# Celery task settings
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERy_TASK_TIME_LIMIT = (7200,)  # 2 hours max per task
CELERY_TASK_STARTED = True
CELERY_SOFT_TIME_LIMIT = (6900,)  # Soft limit at 1h 55m
CELERY_TIMEZONE = "UTC"
CELERY_ENABLE_UTC = True

# Celery Beat settings
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

# Task routing
CELERY_TASK_ROUTES = {
    # 'creator.tasks.*': {'queue': 'creator'},
    # 'creator.tasks.process_media_task': {'queue': 'media_processing'},
    # 'creator.tasks.process_queued_media': {'queue': 'process_queued_media'},
    # 'creator.tasks.cleanup_*': {'queue': 'maintenance'},
}

# Task time limits (30 minutes for scraping tasks)
CELERY_TASK_TIME_LIMIT = 1800
CELERY_TASK_SOFT_TIME_LIMIT = 1500


# File upload settings
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB
DATA_UPLOAD_MAX_MEMORY_SIZE = FILE_UPLOAD_MAX_MEMORY_SIZE


CORS_ORIGIN_WHITELIST = [
    "http://localhost:3000",
    "http://localhost:8000",
    "http://localhost:8200",
    "http://127.0.0.1:8200",
    "http://127.0.0.1:8080",
    f"https://{BASE_DOMAIN}",
    "https://logsng.tech",
    "https://www.logsng.tech",
]

CORS_ORIGIN_REGEX_WHITELIST = [
    r"^https://[\w\-]+\.api\.logsng\.tech$",  # all tenant subdomains
    r"^https://[\w\-]+\.logsng\.tech$",        # any other frontend subdomains
]

# Explicitly list allowed request headers so browser preflights pass.
# The default set from corsheaders already includes authorization and content-type;
# listing them here makes the policy visible and easy to extend.
from corsheaders.defaults import default_headers  # noqa: E402

CORS_ALLOW_HEADERS = list(default_headers) + [
    "x-tenant-subdomain",  # kept for non-browser / Postman clients
]

CSRF_TRUSTED_ORIGINS = [
    f"https://{BASE_DOMAIN}",
    f"https://*.{BASE_DOMAIN}",
]

if not DEBUG:
    # Hosted behind a TLS-terminating reverse proxy (nginx/Caddy/Cloudflare)
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


REST_FRAMEWORK = {
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 10,
    "NON_FIELD_ERRORS_KEY": "error",
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": datetime.timedelta(minutes=10),
    "REFRESH_TOKEN_LIFETIME": datetime.timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,  # Use this for rolling tokens
    "BLACKLIST_AFTER_ROTATION": True,
}


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "inventory_static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"


STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}


# Resend API (used by utils.Util.send_email — settings.RESEND_API_KEY)
RESEND_API_KEY = config("EMAIL_RESEND_API_KEY")
RESEND_FROM_EMAIL = "LogsInventory <send@lendbox.kanlyte.com>"

# SMTP kept for fallback/development; primary emails go through Resend
EMAIL_USE_TLS = True
EMAIL_HOST = config("EMAIL_SERVER_HOST", default="smtp.gmail.com")
EMAIL_PORT = config("EMAIL_PORT", default="587")
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": f"redis://:{config('REDIS_PASSWORD')}@redis:6379/1",
    }
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "file": {
            "level": "INFO",
            "class": "logging.FileHandler",
            "filename": "inventory_backend.log",
            "formatter": "verbose",
        },
        "console": {
            "level": "INFO",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "loggers": {
        "inventory_logs": {
            "handlers": ["file", "console"],
            "level": "INFO",
            "propagate": True,
        },
        # Dedicated logger for Caddy TLS-ask decisions.
        # Every allow/deny is written at INFO/WARNING so operators can audit
        # which domains Caddy requested certs for and why they were rejected.
        "inventory_logs.caddy": {
            "handlers": ["file", "console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
