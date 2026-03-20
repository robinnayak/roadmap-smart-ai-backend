"""
Django settings for development - simplified & cleaned version
"""

from pathlib import Path
from datetime import timedelta
from decouple import config

BASE_DIR = Path(__file__).resolve().parent.parent
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


def build_logging_config() -> dict:
    return {
        'version': 1,
        'disable_existing_loggers': False,
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
            },
        },
        'loggers': {
            'django': {
                'handlers': ['console'],
                'level': 'INFO',
            },
            'authentication': {
                'handlers': ['console'],
                'level': 'DEBUG',
            },
        },
    }

# =============================================================================
# BASIC SECURITY & DEBUG
# =============================================================================

SECRET_KEY = config('DJANGO_SECRET_KEY', default='django-insecure-...change-me...')

DEBUG = bool_env('DEBUG', default=True)

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
ALLOWED_HOSTS = list(
    dict.fromkeys(
        ['localhost', '127.0.0.1', '::1', '.ngrok-free.app', '.ngrok.app'] + _normalized_env_hosts
    )
)

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
# DATABASE (SQLite for dev — easy & fast)
# =============================================================================

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

STATIC_URL = 'static/'

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
MAX_ACTIVE_DEVICE_SESSIONS = max(
    1, config("MAX_ACTIVE_DEVICE_SESSIONS", default=4, cast=int)
)

# GIE rollout controls
GIE_ROLLOUT_ENABLED = bool_env("GIE_ROLLOUT_ENABLED", default=True)
GIE_DEGRADED_MODE = bool_env("GIE_DEGRADED_MODE", default=False)

# =============================================================================
# LOGGING (console only in the active launch configuration)
# The repository's roadmap/logs/ files are not active file handlers or a
# separate logging subsystem unless explicit handlers are added here later.
# =============================================================================

LOGGING = build_logging_config()

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
