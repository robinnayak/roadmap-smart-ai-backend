from __future__ import annotations

from collections.abc import Mapping


REQUIRED_GOAL_CREATE_FIELDS = (
    "title",
    "primary_category",
    "description",
    "why_do_i_want_this",
    "specific_measurable_target",
    "why_it_matters",
    "target_date",
    "commitment_confirmed",
)


def normalize_why_it_matters(value) -> list[str]:
    if value is None:
        return []

    raw_items: list[str] = []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if "\n" in text:
            raw_items = [part.strip() for part in text.splitlines()]
        else:
            raw_items = [part.strip() for part in text.split(",")]
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                raw_items.append(item.strip())
            elif item is not None:
                raw_items.append(str(item).strip())
    else:
        raw_items = [str(value).strip()]

    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        if not item:
            continue
        if item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return normalized


def normalize_goal_create_payload(payload: Mapping) -> dict:
    normalized = dict(payload)
    normalized["why_it_matters"] = normalize_why_it_matters(payload.get("why_it_matters"))
    return normalized


def list_missing_required_goal_fields(payload: Mapping) -> list[str]:
    impact_dimensions = payload.get("impact_dimensions")
    if not isinstance(impact_dimensions, Mapping):
        impact_dimensions = {}

    missing: list[str] = []
    for field in REQUIRED_GOAL_CREATE_FIELDS:
        if field == "why_it_matters":
            reasons = normalize_why_it_matters(payload.get("why_it_matters"))
            if not reasons:
                missing.append(field)
            continue

        if field == "commitment_confirmed":
            if payload.get("commitment_confirmed") is not True:
                missing.append(field)
            continue

        if field == "why_do_i_want_this":
            value = payload.get(field) or impact_dimensions.get("why_do_i_want_this")
            if not isinstance(value, str) or not value.strip():
                missing.append(field)
            continue

        if field == "specific_measurable_target":
            value = payload.get(field) or impact_dimensions.get("specific_measurable_target")
            if not isinstance(value, str) or not value.strip():
                missing.append(field)
            continue

        value = payload.get(field)
        if isinstance(value, str):
            if not value.strip():
                missing.append(field)
        elif value in (None, ""):
            missing.append(field)

    return missing


def required_goal_fields_error_details(missing_fields: list[str]) -> dict[str, str]:
    messages = {
        "title": "Title is required.",
        "primary_category": "Primary category is required.",
        "description": "Description is required.",
        "why_do_i_want_this": "Why do I want this is required.",
        "specific_measurable_target": "Specific measurable target is required.",
        "why_it_matters": "At least one reason is required for why_it_matters.",
        "target_date": "Target date is required.",
        "commitment_confirmed": "You must accept the goal commitment before creating a goal.",
    }
    return {field: messages.get(field, "This field is required.") for field in missing_fields}
