import os

from django.core.exceptions import ImproperlyConfigured


def get_required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not str(value).strip():
        raise ImproperlyConfigured(f"Missing required environment variable: {name}")
    return str(value).strip()

