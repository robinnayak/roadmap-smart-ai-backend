from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime


COMMITMENT_REQUIRED_FIELDS = (
    "commitment_confirmed",
    "commitment_intent",
    "commitment_effort",
    "commitment_responsibility",
    "signed_name",
    "signed_at",
    "contract_snapshot",
)

REQUIRED_GOAL_CREATE_FIELDS = (
    "title",
    "description",
    "why_do_i_want_this",
    "specific_measurable_target",
    "why_it_matters",
    "target_date",
    *COMMITMENT_REQUIRED_FIELDS,
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


def _is_non_empty_text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_valid_signed_at(value) -> bool:
    if isinstance(value, datetime):
        return True
    if not isinstance(value, str) or not value.strip():
        return False
    candidate = value.strip().replace("Z", "+00:00")
    try:
        datetime.fromisoformat(candidate)
    except ValueError:
        return False
    return True


def list_missing_commitment_fields(payload: Mapping) -> list[str]:
    missing: list[str] = []
    for field in COMMITMENT_REQUIRED_FIELDS:
        if field == "commitment_confirmed":
            if payload.get(field) is not True:
                missing.append(field)
            continue
        if field == "contract_snapshot":
            value = payload.get(field)
            if not isinstance(value, Mapping) or not value:
                missing.append(field)
            continue
        if field == "signed_at":
            if not _is_valid_signed_at(payload.get(field)):
                missing.append(field)
            continue
        if not _is_non_empty_text(payload.get(field)):
            missing.append(field)
    return missing


def extract_goal_commitment_record_data(payload: Mapping) -> dict:
    return {
        "commitment_intent": str(payload["commitment_intent"]).strip(),
        "commitment_effort": str(payload["commitment_effort"]).strip(),
        "commitment_responsibility": str(payload["commitment_responsibility"]).strip(),
        "signed_name": str(payload["signed_name"]).strip(),
        "signed_at": payload["signed_at"],
        "contract_snapshot": payload["contract_snapshot"],
    }


def list_missing_required_goal_fields(payload: Mapping) -> list[str]:
    impact_dimensions = payload.get("impact_dimensions")
    if not isinstance(impact_dimensions, Mapping):
        impact_dimensions = {}
    missing_commitment_fields = set(list_missing_commitment_fields(payload))

    missing: list[str] = []
    for field in REQUIRED_GOAL_CREATE_FIELDS:
        if field == "why_it_matters":
            reasons = normalize_why_it_matters(payload.get("why_it_matters"))
            if not reasons:
                missing.append(field)
            continue

        if field in COMMITMENT_REQUIRED_FIELDS:
            if field in missing_commitment_fields:
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
        "description": "Description is required.",
        "why_do_i_want_this": "Why do I want this is required.",
        "specific_measurable_target": "Specific measurable target is required.",
        "why_it_matters": "At least one reason is required for why_it_matters.",
        "target_date": "Target date is required.",
        "commitment_confirmed": "You must accept the goal commitment before creating a goal.",
        "commitment_intent": "Commitment intent is required.",
        "commitment_effort": "Commitment effort is required.",
        "commitment_responsibility": "Commitment responsibility is required.",
        "signed_name": "Signed name is required.",
        "signed_at": "Signed timestamp must be a valid ISO datetime.",
        "contract_snapshot": "Contract snapshot must be a non-empty JSON object.",
    }
    return {field: messages.get(field, "This field is required.") for field in missing_fields}
