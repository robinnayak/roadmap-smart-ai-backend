import os

from common.env import get_required_env

DEFAULT_OLLAMA_MODEL = "gpt-oss:120b-cloud"
REQUIRED_AI_ENV_VARS = ("OLLAMA_HOST",)


def get_ollama_model() -> str:
    return (os.getenv("OLLAMA_MODEL") or "").strip() or DEFAULT_OLLAMA_MODEL


def get_hierarchy_model() -> str:
    return (os.getenv("HIERARCHY_MODEL") or "").strip() or get_ollama_model()


def get_journeybook_model() -> str:
    return (os.getenv("JOURNEYBOOK_MODEL") or "").strip() or get_ollama_model()


def get_ollama_host() -> str:
    return get_required_env("OLLAMA_HOST")


def get_ollama_request_timeout_seconds() -> float:
    raw = (os.getenv("OLLAMA_REQUEST_TIMEOUT_SECONDS") or "").strip()
    if not raw:
        return 180.0
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 180.0


def get_ollama_max_retries() -> int:
    raw = (os.getenv("OLLAMA_MAX_RETRIES") or "").strip()
    if not raw:
        return 2
    try:
        return max(0, int(raw))
    except ValueError:
        return 2


def get_ollama_retry_backoff_seconds() -> float:
    raw = (os.getenv("OLLAMA_RETRY_BACKOFF_SECONDS") or "").strip()
    if not raw:
        return 0.75
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 0.75


def get_ollama_trust_env() -> bool:
    raw = (os.getenv("OLLAMA_TRUST_ENV") or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    # Default to False to avoid accidental proxying (common source of local loopback failures).
    return False


def get_ai_debug_enabled() -> bool:
    raw = (os.getenv("AI_DEBUG") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def get_missing_ai_env_vars() -> list[str]:
    missing: list[str] = []
    for name in REQUIRED_AI_ENV_VARS:
        if not (os.getenv(name) or "").strip():
            missing.append(name)
    return missing


def build_ai_runtime_error_message() -> str:
    missing = get_missing_ai_env_vars()
    if not missing:
        return "AI runtime is not configured."
    missing_list = ", ".join(missing)
    return (
        f"AI runtime is not configured. Missing environment variable(s): {missing_list}. "
        "Set them in backend environment and restart the server."
    )
