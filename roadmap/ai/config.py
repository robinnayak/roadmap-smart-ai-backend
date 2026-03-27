import os
from dataclasses import dataclass

from decouple import config as env_config

DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "GPT_OSS_120B"
DEFAULT_GROQ_MODEL = "GPT_OSS_120B"
DEFAULT_OPENROUTER_MODEL = "GPT_OSS_120B"

PROVIDER_OLLAMA = "ollama"
PROVIDER_GROQ = "groq"
PROVIDER_OPENROUTER = "openrouter"
SUPPORTED_PROVIDERS = {PROVIDER_OLLAMA, PROVIDER_GROQ, PROVIDER_OPENROUTER}

MODEL_PROVIDER_MAP = {
    "GPT_OSS_120B": {
        PROVIDER_OLLAMA: "gpt-oss:120b-cloud",
        PROVIDER_GROQ: "openai/gpt-oss-120b",
        PROVIDER_OPENROUTER: "openai/gpt-oss-120b",
    },
    "LLAMA_3_3_70B": {
        PROVIDER_OLLAMA: "llama3.3:70b",
        PROVIDER_GROQ: "llama-3.3-70b-versatile",
        PROVIDER_OPENROUTER: "meta-llama/llama-3.3-70b-instruct",
    },
}

TASK_MODEL_ENV_MAP = {
    "goal_hierarchy": "HIERARCHY_MODEL",
    "journeybook": "JOURNEYBOOK_MODEL",
    "timeline_insight": "TIMELINE_MODEL",
    "current_situation": "CURRENT_SITUATION_MODEL",
    "gie_language_refinement": "GIE_LANGUAGE_MODEL",
    "journal": "JOURNAL_MODEL",
    "habit_recommendation": "HABIT_RECOMMENDATION_MODEL",
    "goal_attribute_extraction": "GOAL_ATTRIBUTE_MODEL",
    "goal_category_resolution": "GOAL_CATEGORY_MODEL",
}

TASK_FALLBACK_ENV_MAP = {
    "goal_hierarchy": "HIERARCHY_FALLBACKS",
    "journeybook": "JOURNEYBOOK_FALLBACKS",
    "timeline_insight": "TIMELINE_FALLBACKS",
    "current_situation": "CURRENT_SITUATION_FALLBACKS",
    "gie_language_refinement": "GIE_LANGUAGE_FALLBACKS",
    "journal": "JOURNAL_FALLBACKS",
    "habit_recommendation": "HABIT_RECOMMENDATION_FALLBACKS",
    "goal_attribute_extraction": "GOAL_ATTRIBUTE_FALLBACKS",
    "goal_category_resolution": "GOAL_CATEGORY_FALLBACKS",
}


@dataclass(frozen=True)
class ProviderRoute:
    provider_name: str
    model: str


def _get_env_value(name: str) -> str:
    if not name:
        return ""
    direct_value = (os.getenv(name) or "").strip()
    if direct_value:
        return direct_value

    try:
        return (env_config(name, default="") or "").strip()
    except Exception:
        return ""


def get_ollama_model() -> str:
    return get_model_id(_get_env_value("OLLAMA_MODEL") or DEFAULT_OLLAMA_MODEL, PROVIDER_OLLAMA)


def get_hierarchy_model() -> str:
    return get_model_for_task("goal_hierarchy")


def get_journeybook_model() -> str:
    return get_model_for_task("journeybook")


def get_groq_api_key() -> str:
    return _get_env_value("GROQ_API_KEY")


def get_groq_base_url() -> str:
    return _get_env_value("GROQ_BASE_URL") or "https://api.groq.com/openai/v1"


def get_groq_model() -> str:
    return get_model_id(_get_env_value("GROQ_MODEL") or DEFAULT_GROQ_MODEL, PROVIDER_GROQ)


def get_openrouter_api_key() -> str:
    return _get_env_value("OPENROUTER_API_KEY")


def get_openrouter_base_url() -> str:
    return _get_env_value("OPENROUTER_BASE_URL") or "https://openrouter.ai/api/v1"


def get_openrouter_model() -> str:
    return get_model_id(
        _get_env_value("OPENROUTER_MODEL") or DEFAULT_OPENROUTER_MODEL,
        PROVIDER_OPENROUTER,
    )


def get_openrouter_app_name() -> str:
    return _get_env_value("OPENROUTER_APP_NAME") or "Roadmap Smart Planner"


def get_openrouter_site_url() -> str:
    return _get_env_value("OPENROUTER_SITE_URL")


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


def get_llm_request_timeout_seconds() -> float:
    raw = _get_env_value("LLM_REQUEST_TIMEOUT_SECONDS")
    if not raw:
        return 60.0
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 60.0
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


def get_llm_max_retries() -> int:
    raw = _get_env_value("LLM_MAX_RETRIES")
    if not raw:
        return 1
    try:
        return max(0, int(raw))
    except ValueError:
        return 1
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


def get_llm_retry_backoff_seconds() -> float:
    raw = _get_env_value("LLM_RETRY_BACKOFF_SECONDS")
    if not raw:
        return 1.0
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 1.0
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


def get_debug_enabled() -> bool:
    raw = _get_env_value("DEBUG").lower()
    return raw in {"1", "true", "yes", "on", "debug", "dev", "development"}


def get_llm_primary_provider() -> str:
    configured = (_get_env_value("LLM_PRIMARY_PROVIDER") or "").strip().lower()
    if configured in SUPPORTED_PROVIDERS:
        return configured
    return PROVIDER_OLLAMA if get_debug_enabled() else PROVIDER_GROQ


def _coerce_provider_name(name: str | None) -> str:
    candidate = (name or "").strip().lower()
    if candidate in SUPPORTED_PROVIDERS:
        return candidate
    raise ValueError(f"Unsupported LLM provider '{name}'. Supported providers: {sorted(SUPPORTED_PROVIDERS)}")


def _canonicalize_model_key(model_name: str) -> str:
    candidate = (model_name or "").strip()
    if not candidate:
        return candidate
    if candidate in MODEL_PROVIDER_MAP:
        return candidate
    for generic_key, provider_map in MODEL_PROVIDER_MAP.items():
        if candidate in provider_map.values():
            return generic_key
    return candidate


def get_model_id(generic_key: str, provider_name: str) -> str:
    provider = _coerce_provider_name(provider_name)
    key = _canonicalize_model_key(generic_key)
    if not key:
        return key
    return MODEL_PROVIDER_MAP.get(key, {}).get(provider, key)


def get_default_model_for_provider(provider_name: str) -> str:
    provider = _coerce_provider_name(provider_name)
    if provider == PROVIDER_OLLAMA:
        return get_ollama_model()
    if provider == PROVIDER_GROQ:
        return get_groq_model()
    return get_openrouter_model()


def get_model_for_task(task_name: str, provider_name: str | None = None) -> str:
    provider = _coerce_provider_name(provider_name or get_llm_primary_provider())
    env_name = TASK_MODEL_ENV_MAP.get(task_name)
    if env_name:
        configured = _get_env_value(env_name)
        if configured:
            return get_model_id(configured, provider)
    return get_default_model_for_provider(provider)


def _parse_fallbacks(raw: str) -> list[ProviderRoute]:
    routes: list[ProviderRoute] = []
    for item in raw.replace("|", ",").split(","):
        chunk = item.strip()
        if not chunk:
            continue
        if ":" in chunk:
            provider_name, model = chunk.split(":", 1)
            resolved_provider = _coerce_provider_name(provider_name)
            routes.append(
                ProviderRoute(
                    provider_name=resolved_provider,
                    model=get_model_id(model.strip(), resolved_provider)
                    or get_default_model_for_provider(resolved_provider),
                )
            )
            continue
        provider_name = _coerce_provider_name(chunk)
        routes.append(
            ProviderRoute(
                provider_name=provider_name,
                model=get_default_model_for_provider(provider_name),
            )
        )
    return routes


def get_fallback_routes(task_name: str) -> list[ProviderRoute]:
    task_specific_env = TASK_FALLBACK_ENV_MAP.get(task_name)
    task_specific = _get_env_value(task_specific_env) if task_specific_env else ""
    if task_specific:
        return _parse_fallbacks(task_specific)
    global_fallbacks = _get_env_value("LLM_FALLBACKS")
    if global_fallbacks:
        return _parse_fallbacks(global_fallbacks)

    primary = get_llm_primary_provider()
    if primary == PROVIDER_OLLAMA:
        return []
    routes = [ProviderRoute(provider_name=PROVIDER_OPENROUTER, model=get_openrouter_model())]
    if get_debug_enabled() or _get_env_value("OLLAMA_HOST"):
        routes.append(ProviderRoute(provider_name=PROVIDER_OLLAMA, model=get_ollama_model()))
    return routes


def get_provider_routes(
    *,
    task_name: str,
    provider_name: str | None = None,
    model: str | None = None,
) -> list[ProviderRoute]:
    primary_provider = _coerce_provider_name(provider_name or get_llm_primary_provider())
    primary_model = get_model_id((model or "").strip(), primary_provider) or get_model_for_task(
        task_name, primary_provider
    )
    routes = [ProviderRoute(provider_name=primary_provider, model=primary_model)]
    for fallback in get_fallback_routes(task_name):
        if fallback.provider_name == primary_provider and fallback.model == primary_model:
            continue
        if fallback not in routes:
            routes.append(fallback)
    return routes


def get_missing_provider_env_vars(provider_name: str) -> list[str]:
    provider = _coerce_provider_name(provider_name)
    if provider == PROVIDER_OLLAMA:
        return [] if get_ollama_host() else ["OLLAMA_HOST"]
    if provider == PROVIDER_GROQ:
        return [] if get_groq_api_key() else ["GROQ_API_KEY"]
    return [] if get_openrouter_api_key() else ["OPENROUTER_API_KEY"]


def get_missing_ai_env_vars(task_name: str | None = None) -> list[str]:
    routes = get_provider_routes(task_name=task_name or "current_situation")
    primary_missing: list[str] = []
    for index, route in enumerate(routes):
        missing = get_missing_provider_env_vars(route.provider_name)
        if not missing:
            return []
        if index == 0:
            primary_missing = missing
    return primary_missing


def build_ai_runtime_error_message() -> str:
    missing = get_missing_ai_env_vars()
    if not missing:
        return "AI runtime is not configured."
    missing_list = ", ".join(missing)
    return (
        f"AI runtime is not configured. Missing environment variable(s): {missing_list}. "
        "Set them in backend environment and restart the server."
    )
