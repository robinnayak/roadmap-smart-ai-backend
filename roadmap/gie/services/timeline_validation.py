from __future__ import annotations

from dataclasses import dataclass

from django.utils import timezone

from gie.models import GIESession, GIESlotState
from goal.services.timeline_deterministic import compute_timeline_realism, parse_iso_date

TIMELINE_REFRAME_ANALYSIS_KEY = "__timeline_reframe_analysis"
TIMELINE_REFRAME_DECISION_KEY = "__timeline_reframe_decision"

DECISION_ACCEPT = "accept_reframed_plan"
DECISION_ADJUST = "adjust_manually"


@dataclass(frozen=True)
class TimelineValidationResult:
    verdict: str
    achievable_sub_goal: str
    projected_full_goal_completion_date: str
    impact_percent: float
    stated_timeline_days: int
    estimated_timeline_days: int

    @property
    def needs_reframe(self) -> bool:
        return self.verdict == "unrealistic"


class GIETimelineValidationService:
    """Deterministic timeline realism check with domain + health profile constraints."""

    @classmethod
    def evaluate(
        cls,
        *,
        session: GIESession,
        slot_states_by_key: dict[str, GIESlotState],
        health_profile,
    ) -> TimelineValidationResult | None:
        timeline_state = slot_states_by_key.get("timeline_target_date")
        timeline_value = timeline_state.value if timeline_state else None
        if not timeline_value:
            return None

        target_date = parse_iso_date(timeline_value)
        if not target_date:
            return None

        today = timezone.localdate()
        stated_timeline_days = max(1, (target_date - today).days)
        slot_values = {key: state.value for key, state in slot_states_by_key.items()}
        realism = compute_timeline_realism(
            goal_domain=session.goal_domain,
            slot_values=slot_values,
            health_profile=health_profile,
            stated_timeline_days=stated_timeline_days,
            today=today,
        )

        return TimelineValidationResult(
            verdict=realism["verdict"],
            achievable_sub_goal=realism["achievable_sub_goal"],
            projected_full_goal_completion_date=realism["projected_full_goal_completion_date"],
            impact_percent=realism["impact_percent"],
            stated_timeline_days=realism["stated_timeline_days"],
            estimated_timeline_days=realism["estimated_timeline_days"],
        )
