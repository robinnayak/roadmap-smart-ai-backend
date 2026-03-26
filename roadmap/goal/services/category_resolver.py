import logging
import re

from django.core.exceptions import ImproperlyConfigured

from ai.config import get_missing_ai_env_vars, get_model_for_task
from ai.providers.router import create_routed_provider
from ai.utils.parsers import ResponseParser


logger = logging.getLogger(__name__)

GOAL_CATEGORIES = (
    "business",
    "fitness",
    "learning",
    "wellness",
    "creative",
    "nutrition",
    "productivity",
    "travel",
    "digital_habits",
    "spiritual",
    "relationships",
    "education",
    "career",
    "finance",
    "parenting",
)

GOAL_CATEGORY_CHOICES = [(category, category.replace("_", " ").title()) for category in GOAL_CATEGORIES]
DEFAULT_GOAL_CATEGORY = "productivity"
LEGACY_TO_CANONICAL_CATEGORY = {
    "financial": "finance",
    "finance": "finance",
    "career": "career",
    "health": "fitness",
    "personal": "productivity",
}

ATTRIBUTE_HEALTH_CATEGORIES = {"fitness", "wellness", "nutrition"}
FINANCE_CATEGORY_ALIASES = {"finance", "financial"}
PERSONAL_FALLBACK_CATEGORIES = {"personal", "productivity"}

TOKEN_PATTERN = re.compile(r"\b[\w']+\b")
STEM_SIGNALS = {"meditat", "illustrat"}

CATEGORY_SIGNALS = {
    "business": [
        "mvp", "launch", "startup", "revenue", "customers", "deploy", "product",
        "saas", "side hustle", "freelance", "ship", "beta", "users", "monetise",
        "monetize", "founder", "business",
    ],
    "fitness": [
        "run", "marathon", "gym", "weight loss", "workout", "training", "race",
        "cycling", "swimming", "athletic", "5k", "10k", "triathlon", "lift",
        "squat", "bench", "half marathon",
    ],
    "learning": [
        "learn", "course", "certification", "study", "skill", "tutorial", "module",
        "lecture", "machine learning", "python", "javascript",
    ],
    "wellness": [
        "stress", "anxiety", "sleep", "meditation", "mental health", "therapy",
        "mindfulness", "burnout", "sobriety", "sober",
    ],
    "creative": [
        "write", "novel", "music", "art", "design", "photography", "film", "blog",
        "podcast", "draw", "illustrat", "paint", "creative",
    ],
    "nutrition": [
        "diet", "meal prep", "calories", "protein", "eat", "food", "vegan",
        "nutrition", "cook", "macro",
    ],
    "productivity": [
        "focus", "deep work", "procrastination", "system", "distraction",
        "time management", "productivity", "routine", "organize",
    ],
    "travel": [
        "trip", "travel", "visit", "country", "flight", "holiday", "sabbatical",
        "backpack", "itinerary",
    ],
    "digital_habits": [
        "screen time", "phone", "social media", "detox", "notifications",
        "instagram", "scroll", "digital", "youtube",
    ],
    "spiritual": [
        "prayer", "gratitude", "spiritual", "faith", "mindfulness", "meditat",
        "purpose", "meaning", "stoic", "church",
    ],
    "relationships": [
        "partner", "family", "communication", "social", "dating", "friendship",
        "parent", "marriage", "connect", "relationship",
    ],
    "education": [
        "degree", "university", "thesis", "dissertation", "gpa", "semester",
        "exam", "college", "phd", "masters", "master's", "school",
    ],
    "career": [
        "job", "promotion", "salary", "interview", "linkedin", "portfolio",
        "hire", "role", "engineer", "manager", "career",
    ],
    "finance": [
        "save", "debt", "invest", "budget", "money", "fund", "financial",
        "emergency fund", "credit", "mortgage", "retirement", "savings",
    ],
    "parenting": [
        "parenting", "parent", "kids", "children", "child", "co-parent",
        "mother", "father", "son", "daughter",
    ],
}


def is_valid_goal_category(value: str | None) -> bool:
    return bool(value and value in GOAL_CATEGORIES)


def normalize_goal_category(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized in GOAL_CATEGORIES:
        return normalized
    return LEGACY_TO_CANONICAL_CATEGORY.get(normalized)


def normalize_goal_category_or_default(
    value: str | None,
    *,
    default: str = DEFAULT_GOAL_CATEGORY,
) -> str:
    return normalize_goal_category(value) or default


def normalize_goal_category_for_query(value: str | None) -> str | None:
    return normalize_goal_category(value)


def normalize_goal_category_for_storage(
    value: str | None,
    *,
    goal_title: str = "",
    goal_description: str = "",
) -> str:
    normalized = normalize_goal_category(value)
    if normalized:
        return normalized
    if isinstance(value, str) and value.strip():
        return classify_goal_category_deterministic(
            goal_title=goal_title,
            goal_description=goal_description,
            current_category=value,
        )
    return DEFAULT_GOAL_CATEGORY


def is_finance_goal_category(value: str | None) -> bool:
    return normalize_goal_category(value) == "finance"


def get_goal_attribute_bucket(value: str | None) -> str:
    normalized = normalize_goal_category(value) or DEFAULT_GOAL_CATEGORY
    if normalized == "finance":
        return "financial_data"
    if normalized == "career":
        return "career_data"
    if normalized in ATTRIBUTE_HEALTH_CATEGORIES:
        return "health_data"
    return "personal_data"


def classify_goal_category(*, goal_title: str, goal_description: str = "", current_category: str | None = None) -> str:
    llm_category = _classify_with_llm(goal_title=goal_title, goal_description=goal_description)
    if is_valid_goal_category(llm_category):
        return llm_category

    return classify_goal_category_deterministic(
        goal_title=goal_title,
        goal_description=goal_description,
        current_category=current_category,
    )


def classify_goal_category_deterministic(*, goal_title: str, goal_description: str = "", current_category: str | None = None) -> str:
    text = f"{goal_title} {goal_description}".strip()
    normalized_current = normalize_goal_category(current_category)
    if normalized_current == "finance":
        return "finance"
    if normalized_current == "career":
        return _try_upgrade("career", text)
    if normalized_current == "fitness":
        return _try_upgrade("fitness", text)
    return _classify_from_text(text)


def resolve_category(frontend_category: str, goal_title: str, goal_description: str) -> str:
    return normalize_goal_category_for_storage(
        frontend_category,
        goal_title=goal_title,
        goal_description=goal_description,
    )


def _classify_with_llm(*, goal_title: str, goal_description: str) -> str | None:
    if get_missing_ai_env_vars(task_name="goal_category_resolution"):
        return None

    prompt = (
        "Classify this goal into exactly one category.\n"
        f"Allowed categories: {', '.join(GOAL_CATEGORIES)}.\n"
        "Return valid JSON only in the form {\"category\": \"one_allowed_value\"}.\n"
        f"Title: {goal_title}\n"
        f"Description: {goal_description}\n"
    )
    try:
        provider = create_routed_provider(
            task_name="goal_category_resolution",
            model=get_model_for_task("goal_category_resolution"),
            temperature=0.0,
            max_tokens=80,
        )
        response = provider.generate_response(
            prompt=prompt,
            system_prompt=(
                "You are a goal classification engine. "
                "Choose exactly one allowed category. "
                "Do not explain your answer."
            ),
        )
        parsed = ResponseParser.parse_json(response.content)
        if isinstance(parsed, dict):
            return normalize_goal_category(parsed.get("category"))
        if isinstance(parsed, str):
            return normalize_goal_category(parsed)
    except ImproperlyConfigured:
        return None
    except Exception as exc:
        logger.warning("LLM goal classification failed for '%s': %s", goal_title[:80], exc)
    return None


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.lower())


def _matches_signal(signal: str, normalized_text: str, tokens: list[str], token_set: set[str]) -> bool:
    normalized_signal = signal.lower()
    if " " in normalized_signal:
        pattern = rf"(?<!\w){re.escape(normalized_signal)}(?!\w)"
        return re.search(pattern, normalized_text) is not None
    if normalized_signal in STEM_SIGNALS:
        return any(token.startswith(normalized_signal) for token in tokens)
    return normalized_signal in token_set


def _score_signals(keywords: list[str], normalized_text: str, tokens: list[str], token_set: set[str]) -> int:
    return sum(1 for keyword in keywords if _matches_signal(keyword, normalized_text, tokens, token_set))


def _classify_from_text(text: str) -> str:
    normalized_text = _normalize_text(text)
    tokens = _tokenize(normalized_text)
    token_set = set(tokens)
    scores = {
        category: _score_signals(keywords, normalized_text, tokens, token_set)
        for category, keywords in CATEGORY_SIGNALS.items()
    }
    best_category = max(scores, key=scores.get)
    if scores[best_category] <= 0:
        return DEFAULT_GOAL_CATEGORY
    return best_category


def _try_upgrade(base: str, text: str) -> str:
    normalized_text = _normalize_text(text)
    tokens = _tokenize(normalized_text)
    token_set = set(tokens)

    if base == "career":
        business_score = _score_signals(CATEGORY_SIGNALS["business"], normalized_text, tokens, token_set)
        career_score = _score_signals(CATEGORY_SIGNALS["career"], normalized_text, tokens, token_set)
        if business_score > career_score:
            return "business"

    if base == "fitness":
        nutrition_score = _score_signals(CATEGORY_SIGNALS["nutrition"], normalized_text, tokens, token_set)
        fitness_score = _score_signals(CATEGORY_SIGNALS["fitness"], normalized_text, tokens, token_set)
        if nutrition_score > fitness_score:
            return "nutrition"

    return base
