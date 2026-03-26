"""
Django settings for development - simplified & cleaned version
"""

import importlib.util
import sys
from pathlib import Path
from datetime import timedelta
from decouple import config
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
IS_TESTING = any(arg in {"test", "pytest"} for arg in sys.argv)
JSON_RENDERER_CLASS = 'common.renderers.ContractJSONRenderer'
BROWSABLE_RENDERER_CLASS = 'rest_framework.renderers.BrowsableAPIRenderer'


def bool_env(name: str, default: bool = False) -> bool:
    """Parse truthy/falsy env values with support for deployment aliases."""
    raw = config(name, default=str(default))
    if isinstance(raw, bool):
        return raw
    value = str(raw).strip().lower()
    truthy = {"1", "true", "t", "yes", "y", "on", "debug", "dev", "development"}
    falsy = {"0", "false", "f", "no", "n", "off", "prod", "production", "release"}
    if value in truthy:
        return True
    if value in falsy:
        return False
    raise ValueError(f"Invalid boolean value for {name}: {raw!r}")


def build_default_renderer_classes(*, debug: bool) -> list[str]:
    classes = [JSON_RENDERER_CLASS]
    if debug:
        classes.append(BROWSABLE_RENDERER_CLASS)
    return classes


def build_logging_config(*, debug: bool | None = None, django_env: str | None = None) -> dict:
    if debug is None:
        debug = DEBUG
    if django_env is None:
        django_env = DJANGO_ENV
    return {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'standard': {
                'format': '%(asctime)s %(levelname)s %(name)s %(message)s',
            },
            'verbose': {
                'format': '%(asctime)s %(levelname)s %(name)s env=%(processName)s %(message)s',
            },
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'formatter': 'standard' if debug else 'verbose',
            },
        },
        'root': {
            'handlers': ['console'],
            'level': 'DEBUG' if debug else 'INFO',
        },
        'loggers': {
            'django': {
                'handlers': ['console'],
                'level': 'INFO',
                'propagate': False,
            },
            'authentication': {
                'handlers': ['console'],
                'level': 'DEBUG' if debug else 'INFO',
                'propagate': False,
            },
            'ai': {
                'handlers': ['console'],
                'level': 'DEBUG' if debug else 'INFO',
                'propagate': False,
            },
            'goal': {
                'handlers': ['console'],
                'level': 'DEBUG' if debug else 'INFO',
                'propagate': False,
            },
            'journeybook': {
                'handlers': ['console'],
                'level': 'DEBUG' if debug else 'INFO',
                'propagate': False,
            },
        },
    }

# =============================================================================
# BASIC SECURITY & DEBUG
# =============================================================================

SECRET_KEY = config('DJANGO_SECRET_KEY', default='django-insecure-...change-me...')
HUGGINGFACE_API_KEY = config("HUGGINGFACE_API_KEY", default="")
AI_DEBUG = bool_env("AI_DEBUG", default=False)
CI_USE_SQLITE = bool_env("CI_USE_SQLITE", default=False)
DJANGO_ENV = config("DJANGO_ENV", default="development").strip() or "development"
SENTRY_DSN = config("SENTRY_DSN", default="").strip()
DISABLE_SENTRY = bool_env("DISABLE_SENTRY", default=CI_USE_SQLITE)
SENTRY_TRACES_SAMPLE_RATE = config("SENTRY_TRACES_SAMPLE_RATE", default=0.0, cast=float)
SENTRY_PROFILES_SAMPLE_RATE = config("SENTRY_PROFILES_SAMPLE_RATE", default=0.0, cast=float)
SENTRY_SEND_DEFAULT_PII = bool_env("SENTRY_SEND_DEFAULT_PII", default=False)
HAS_WHITENOISE = importlib.util.find_spec("whitenoise") is not None

DEBUG = bool_env('DEBUG', default=False)

_env_allowed_hosts = [host.strip() for host in config('ALLOWED_HOSTS', default='').split(',') if host.strip()]


def _normalize_allowed_host(host: str) -> str:
    """
    Django supports subdomain wildcards as '.example.com', not '*.example.com'.
    """
    cleaned = host.strip()
    if cleaned.startswith("*."):
        return f".{cleaned[2:]}"
    return cleaned


_normalized_env_hosts = [_normalize_allowed_host(host) for host in _env_allowed_hosts]
_local_allowed_hosts = ['localhost', '127.0.0.1', '::1', '.ngrok-free.app', '.ngrok.app']
ALLOWED_HOSTS = list(dict.fromkeys(_local_allowed_hosts + _normalized_env_hosts))

# =============================================================================
# INSTALLED_APPS & MIDDLEWARE
# =============================================================================

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'django_filters',
    'corsheaders',

    'authentication.apps.AuthenticationConfig',
    'goal.apps.GoalConfig',
    'ai.apps.AiConfig',
    'routine.apps.RoutineConfig',
    'base.apps.BaseConfig',
    'journeybook.apps.JourneybookConfig',
    'journal.apps.JournalConfig',
    'community.apps.CommunityConfig',
    'events',
    'gie.apps.GieConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'common.middleware.wake_tracking.WakeInteractionTrackingMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

if HAS_WHITENOISE:
    MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')

# =============================================================================
# URLS & TEMPLATES
# =============================================================================

ROOT_URLCONF = 'roadmap.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'roadmap.wsgi.application'

# =============================================================================
# DATABASE
# =============================================================================

DB_ENGINE = '' if CI_USE_SQLITE else config('DB_ENGINE', default='').strip()

if DB_ENGINE:
    DATABASES = {
        'default': {
            'ENGINE': DB_ENGINE,
            'NAME': config('DB_NAME', default=''),
            'USER': config('DB_USER', default=''),
            'PASSWORD': config('DB_PASSWORD', default=''),
            'HOST': config('DB_HOST', default='localhost'),
            'PORT': config('DB_PORT', default=5432, cast=int),
            'CONN_MAX_AGE': config('DB_CONN_MAX_AGE', default=60, cast=int),
            'CONN_HEALTH_CHECKS': bool_env('DB_CONN_HEALTH_CHECKS', default=True),
        }
    }
    db_sslmode = config('DB_SSLMODE', default='').strip()
    if db_sslmode:
        DATABASES['default']['OPTIONS'] = {'sslmode': db_sslmode}
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
            'OPTIONS': {'timeout': 20},
        }
    }

# =============================================================================
# PASSWORD VALIDATION
# =============================================================================

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# =============================================================================
# INTERNATIONALIZATION
# =============================================================================

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# =============================================================================
# STATIC FILES
# =============================================================================

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# =============================================================================
# CUSTOM USER MODEL
# =============================================================================

AUTH_USER_MODEL = 'authentication.CustomUser'

# =============================================================================
# CORS (frontend communication)
# =============================================================================

CORS_ALLOWED_ORIGINS = [
    'http://localhost:3000',
    'http://127.0.0.1:3000',
] + [
    origin.strip()
    for origin in config('CORS_ALLOWED_ORIGINS', default='').split(',')
    if origin.strip()
]

CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^https://[a-z0-9-]+\.ngrok-free\.app$",
    r"^https://[a-z0-9-]+\.ngrok\.app$",
]

CORS_ALLOW_CREDENTIALS = True

CORS_ALLOW_METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS']
CORS_ALLOW_HEADERS = [
    'authorization',
    'content-type',
    'accept',
    'x-csrftoken',
    'x-requested-with',
    'x-user-timezone',
]

# =============================================================================
# REST FRAMEWORK + JWT
# =============================================================================

REST_FRAMEWORK = {
    # Launch auth contract: JWT is the supported application auth mechanism.
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
    # Production stays JSON-only; the browsable API is added only in DEBUG below.
    'DEFAULT_RENDERER_CLASSES': build_default_renderer_classes(debug=False),
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/day',
        'user': '1000/day',
    },
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=config('ACCESS_TOKEN_LIFETIME_MINUTES', default=1, cast=int)),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=config('REFRESH_TOKEN_LIFETIME_DAYS', default=7, cast=int)),
    
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': False,
    
    'AUTH_HEADER_TYPES': ('Bearer',),
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
}

# Maximum number of concurrently active refresh-token sessions per user (device cap).
MAX_ACTIVE_DEVICE_SESSIONS = config("MAX_ACTIVE_DEVICE_SESSIONS", default=0, cast=int)

# GIE rollout controls
GIE_ROLLOUT_ENABLED = bool_env("GIE_ROLLOUT_ENABLED", default=True)
GIE_DEGRADED_MODE = bool_env("GIE_DEGRADED_MODE", default=False)

# =============================================================================
# LOGGING (console only in the active launch configuration)
# The repository's roadmap/logs/ files are not active file handlers or a
# separate logging subsystem unless explicit handlers are added here later.
# =============================================================================

LOGGING = build_logging_config(debug=DEBUG, django_env=DJANGO_ENV)

# =============================================================================
# DEVELOPMENT CONVENIENCE
# =============================================================================

if DEBUG:
    # Debug-only developer surface: browsable API renderer and /api-auth/ routes.
    # Production remains JSON-only and JWT-only for supported app auth.
    REST_FRAMEWORK['DEFAULT_RENDERER_CLASSES'] = build_default_renderer_classes(debug=True)
    
    # Longer tokens during dev (optional — comment out if you want short tokens)
    # SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'] = timedelta(days=1)
    # SIMPLE_JWT['REFRESH_TOKEN_LIFETIME'] = timedelta(days=30)

# =============================================================================
# RESEND / CONTRACT DELIVERY
# =============================================================================

RESEND_API_KEY = config("RESEND_API_KEY", default="")
RESEND_FROM_EMAIL = config(
    "RESEND_FROM_EMAIL",
    default="Roadmap Smart Planner <onboarding@resend.dev>",
)

# =============================================================================
# EMAIL / PASSWORD RESET
# =============================================================================

EMAIL_BACKEND = config(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_HOST = config("EMAIL_HOST", default="")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_USE_TLS = bool_env("EMAIL_USE_TLS", default=True)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="noreply@example.com")
PASSWORD_RESET_URL = config("PASSWORD_RESET_URL", default="")

# =============================================================================
# REDIS / CELERY
# =============================================================================

REDIS_URL = config("REDIS_URL", default="").strip()
CELERY_TASK_ALWAYS_EAGER = bool_env(
    "CELERY_TASK_ALWAYS_EAGER",
    default=(DEBUG or IS_TESTING or not bool(REDIS_URL)),
)
CELERY_TASK_EAGER_PROPAGATES = bool_env(
    "CELERY_TASK_EAGER_PROPAGATES",
    default=DEBUG,
)
if REDIS_URL:
    CELERY_BROKER_URL = REDIS_URL
    CELERY_RESULT_BACKEND = REDIS_URL
else:
    CELERY_BROKER_URL = "memory://"
    CELERY_RESULT_BACKEND = "cache+memory://"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

# =============================================================================
# OBJECT STORAGE
# =============================================================================

USE_R2_STORAGE = bool_env("USE_R2_STORAGE", default=False)
if USE_R2_STORAGE:
    INSTALLED_APPS.append("storages")
    R2_ENDPOINT_URL = config("R2_ENDPOINT_URL", default="").strip()
    R2_BUCKET_NAME = config("R2_BUCKET_NAME", default="").strip()
    R2_ACCESS_KEY_ID = config("R2_ACCESS_KEY_ID", default="").strip()
    R2_SECRET_ACCESS_KEY = config("R2_SECRET_ACCESS_KEY", default="").strip()
    R2_PUBLIC_BASE_URL = config("R2_PUBLIC_BASE_URL", default="").strip()
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                "access_key": R2_ACCESS_KEY_ID,
                "secret_key": R2_SECRET_ACCESS_KEY,
                "bucket_name": R2_BUCKET_NAME,
                "endpoint_url": R2_ENDPOINT_URL,
                "region_name": "auto",
                "default_acl": None,
                "querystring_auth": False,
                "file_overwrite": False,
            },
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
            if HAS_WHITENOISE
            else "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
    if R2_PUBLIC_BASE_URL:
        MEDIA_URL = f"{R2_PUBLIC_BASE_URL.rstrip('/')}/"
else:
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
            if HAS_WHITENOISE
            else "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }

WHITENOISE_AUTOREFRESH = DEBUG
WHITENOISE_USE_FINDERS = DEBUG
WHITENOISE_MAX_AGE = config("WHITENOISE_MAX_AGE", default=31536000, cast=int)

if not DEBUG:
    SECURE_SSL_REDIRECT = bool_env("SECURE_SSL_REDIRECT", default=True)
    SESSION_COOKIE_SECURE = bool_env("SESSION_COOKIE_SECURE", default=True)
    CSRF_COOKIE_SECURE = bool_env("CSRF_COOKIE_SECURE", default=True)
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_HSTS_SECONDS = config("SECURE_HSTS_SECONDS", default=31536000, cast=int)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = bool_env("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True)
    SECURE_HSTS_PRELOAD = bool_env("SECURE_HSTS_PRELOAD", default=True)


def _require_non_empty_setting(name: str) -> None:
    value = globals().get(name)
    if value is None or not str(value).strip():
        raise ImproperlyConfigured(f"{name} must be configured when DEBUG=False.")


if not DEBUG and not IS_TESTING:
    for setting_name in ("RESEND_API_KEY", "RESEND_FROM_EMAIL", "PASSWORD_RESET_URL"):
        _require_non_empty_setting(setting_name)
    if not REDIS_URL and not CELERY_TASK_ALWAYS_EAGER:
        raise ImproperlyConfigured(
            "REDIS_URL must be configured when Celery eager mode is disabled."
        )
    if USE_R2_STORAGE:
        for setting_name in (
            "R2_ENDPOINT_URL",
            "R2_BUCKET_NAME",
            "R2_ACCESS_KEY_ID",
            "R2_SECRET_ACCESS_KEY",
            "R2_PUBLIC_BASE_URL",
        ):
            _require_non_empty_setting(setting_name)

if SENTRY_DSN and not DISABLE_SENTRY:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.django import DjangoIntegration

        sentry_integrations = [DjangoIntegration()]
        if importlib.util.find_spec("celery") is not None:
            from sentry_sdk.integrations.celery import CeleryIntegration

            sentry_integrations.append(CeleryIntegration())

        sentry_sdk.init(
            dsn=SENTRY_DSN,
            environment=DJANGO_ENV,
            integrations=sentry_integrations,
            traces_sample_rate=SENTRY_TRACES_SAMPLE_RATE,
            profiles_sample_rate=SENTRY_PROFILES_SAMPLE_RATE,
            send_default_pii=SENTRY_SEND_DEFAULT_PII,
        )
    except ImportError:
        pass
