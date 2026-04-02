from goal.services.category_resolver import (
    normalize_goal_category,
    normalize_goal_category_for_storage,
)


_PILLAR_LABELS = (
    "Money",
    "Health",
    "Career",
    "Learning",
    "Relationships",
    "Personal",
)

_CANONICAL_TO_PILLAR = {
    "finance": "Money",
    "fitness": "Health",
    "nutrition": "Health",
    "wellness": "Health",
    "career": "Career",
    "business": "Career",
    "learning": "Learning",
    "education": "Learning",
    "relationships": "Relationships",
    "communication": "Relationships",
    "parenting": "Relationships",
    "productivity": "Personal",
    "digital_habits": "Personal",
    "spiritual": "Personal",
    "creative": "Personal",
    "travel": "Personal",
}

_PILLAR_TO_DEFAULT_CANONICAL = {
    "Money": "finance",
    "Health": "fitness",
    "Career": "career",
    "Learning": "learning",
    "Relationships": "relationships",
    "Personal": "productivity",
}

_PILLAR_ALIASES = {pillar.lower(): pillar for pillar in _PILLAR_LABELS}


def normalize_category_pillar(value) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    normalized = normalized.replace("-", " ").replace("_", " ")
    normalized = " ".join(normalized.split())
    compact = normalized.replace(" ", "")
    if compact in _PILLAR_ALIASES:
        return _PILLAR_ALIASES[compact]
    return _PILLAR_ALIASES.get(normalized)


def canonical_to_pillar(canonical) -> str:
    normalized = normalize_goal_category(canonical)
    if not normalized:
        normalized = normalize_goal_category_for_storage(
            canonical,
            goal_title="",
            goal_description="",
        )
    return _CANONICAL_TO_PILLAR.get(normalized, "Personal")


def pillar_to_default_canonical(pillar) -> str | None:
    normalized = normalize_category_pillar(pillar)
    if not normalized:
        return None
    return _PILLAR_TO_DEFAULT_CANONICAL.get(normalized)


def resolve_canonical_category(primary_category, category_pillar, goal_title, goal_description) -> str:
    normalized_pillar = normalize_category_pillar(category_pillar)

    # Contract rule: explicit canonical input always wins over pillar input.
    if isinstance(primary_category, str) and primary_category.strip():
        return normalize_goal_category_for_storage(
            primary_category,
            goal_title=goal_title or "",
            goal_description=goal_description or "",
        )

    if normalized_pillar:
        return pillar_to_default_canonical(normalized_pillar) or normalize_goal_category_for_storage(
            None,
            goal_title=goal_title or "",
            goal_description=goal_description or "",
        )

    return normalize_goal_category_for_storage(
        primary_category,
        goal_title=goal_title or "",
        goal_description=goal_description or "",
    )
