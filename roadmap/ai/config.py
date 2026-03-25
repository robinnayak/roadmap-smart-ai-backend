import os

from decouple import config as env_config

DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "gpt-oss:120b-cloud"
REQUIRED_AI_ENV_VARS = ("OLLAMA_HOST",)


def _get_env_value(name: str) -> str:
    direct_value = (os.getenv(name) or "").strip()
    if direct_value:
        return direct_value

    try:
        return (env_config(name, default="") or "").strip()
    except Exception:
        return ""


def get_ollama_model() -> str:
    return _get_env_value("OLLAMA_MODEL") or DEFAULT_OLLAMA_MODEL


def get_hierarchy_model() -> str:
    return _get_env_value("HIERARCHY_MODEL") or get_ollama_model()


def get_journeybook_model() -> str:
    return _get_env_value("JOURNEYBOOK_MODEL") or get_ollama_model()


def get_ollama_host() -> str:
    return _get_env_value("OLLAMA_HOST") or DEFAULT_OLLAMA_HOST


def get_ollama_request_timeout_seconds() -> float:
    raw = _get_env_value("OLLAMA_REQUEST_TIMEOUT_SECONDS")
    if not raw:
        return 180.0
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 180.0


def get_ollama_max_retries() -> int:
    raw = _get_env_value("OLLAMA_MAX_RETRIES")
    if not raw:
        return 2
    try:
        return max(0, int(raw))
    except ValueError:
        return 2


def get_ollama_retry_backoff_seconds() -> float:
    raw = _get_env_value("OLLAMA_RETRY_BACKOFF_SECONDS")
    if not raw:
        return 0.75
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 0.75


def get_ollama_trust_env() -> bool:
    raw = _get_env_value("OLLAMA_TRUST_ENV").lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    # Default to False to avoid accidental proxying (common source of local loopback failures).
    return False


def get_ai_debug_enabled() -> bool:
    raw = _get_env_value("AI_DEBUG").lower()
    return raw in {"1", "true", "yes", "on"}


def get_missing_ai_env_vars() -> list[str]:
    missing: list[str] = []
    for name in REQUIRED_AI_ENV_VARS:
        if not _get_env_value(name):
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
