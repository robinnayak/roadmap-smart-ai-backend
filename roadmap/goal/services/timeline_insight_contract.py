from __future__ import annotations

from collections.abc import Iterable


TIMELINE_INSIGHT_TRIGGER_USER_CLICK = "user_click"
ALLOWED_TIMELINE_INSIGHT_TRIGGERS = {TIMELINE_INSIGHT_TRIGGER_USER_CLICK}
GIE_RUNTIME_FLOW_REUSE_ALLOWED = False

# Read-only payload contract for timeline insight analysis requests.
ALLOWED_TIMELINE_INSIGHT_KEYS = {
    "goal_id",
    "trigger_source",
    "context",
}

# Any payload containing these keys violates the no-mutation boundary.
FORBIDDEN_MUTATION_FIELDS = {
    "title",
    "description",
    "status",
    "target_date",
    "start_date",
    "priority",
    "progress_percentage",
    "task_type",
    "item_type",
    "frequency",
    "difficulty_level",
    "session_type",
    "is_prerequisite",
    "sequence_position",
    "rationale",
}


class TimelineInsightBoundaryError(ValueError):
    """Raised when timeline insight contract boundaries are violated."""


def assert_read_only_timeline_insight_request(payload: dict) -> None:
    if not isinstance(payload, dict):
        raise TimelineInsightBoundaryError("Timeline insight payload must be a JSON object.")

    unknown_keys = set(payload.keys()) - ALLOWED_TIMELINE_INSIGHT_KEYS
    if unknown_keys:
        raise TimelineInsightBoundaryError(
            f"Unknown timeline insight payload keys are not allowed: {sorted(unknown_keys)}."
        )

    forbidden_keys = set(payload.keys()) & FORBIDDEN_MUTATION_FIELDS
    if forbidden_keys:
        raise TimelineInsightBoundaryError(
            f"Timeline insight payload cannot include mutation fields: {sorted(forbidden_keys)}."
        )

    trigger_source = payload.get("trigger_source")
    if trigger_source not in ALLOWED_TIMELINE_INSIGHT_TRIGGERS:
        raise TimelineInsightBoundaryError(
            "Timeline insight requests must be click-triggered with trigger_source='user_click'."
        )


def assert_no_gie_runtime_dependency(import_paths: Iterable[str]) -> None:
    if GIE_RUNTIME_FLOW_REUSE_ALLOWED:
        return

    blocked = [path for path in import_paths if isinstance(path, str) and path.startswith("gie.")]
    if blocked:
        raise TimelineInsightBoundaryError(
            f"Direct GIE runtime dependency is forbidden for timeline insight: {sorted(blocked)}."
        )
