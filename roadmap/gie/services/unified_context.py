from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from gie.models import GIESession, GIESlotState
from gie.services.dynamic_schema import (
    WAVE4_DOMAIN_CAREER,
    WAVE4_DOMAIN_FINANCE,
    WAVE4_DOMAIN_RUNNING_ENDURANCE,
    WAVE4_DOMAIN_SKILL_ACQUISITION,
    map_session_domain_to_wave4_domain,
)

DOMAIN_MINIMUM_WEEKS = {
    WAVE4_DOMAIN_RUNNING_ENDURANCE: 12,
    WAVE4_DOMAIN_FINANCE: 4,
    WAVE4_DOMAIN_SKILL_ACQUISITION: 8,
    WAVE4_DOMAIN_CAREER: 26,
}


def _coerce_priority(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"low", "medium", "high"}:
        return normalized
    return "medium"


def _iso_date_or_default(value, fallback_date) -> str:
    if isinstance(value, str) and value:
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return fallback_date.isoformat()


class GIEUnifiedContextService:
    """Builds the authoritative unified context contract from slot state."""

    @classmethod
    def build(cls, *, session: GIESession, slot_states: list[GIESlotState]) -> dict:
        slot_map = {state.slot_key: state for state in slot_states}
        wave_domain = map_session_domain_to_wave4_domain(session.goal_domain, session.goal_text)
        required_keys = cls._required_keys_by_domain(wave_domain)

        missing = [
            key
            for key in required_keys
            if not cls._has_value(slot_map.get(key))
        ]
        completion_status = "complete" if not missing else "incomplete"

        slot_profile: dict = {
            "goal_domain": wave_domain,
            "completion_status": completion_status,
        }
        for key in required_keys:
            slot_profile[key] = cls._slot_value(slot_map.get(key))

        start_date = timezone.localdate()
        end_date = cls._resolve_target_date(slot_map=slot_map, wave_domain=wave_domain, fallback=start_date + timedelta(days=90))
        total_days = max(1, (end_date - start_date).days)
        total_weeks = max(1, int(round(total_days / 7.0)))
        buffer_weeks = 2 if total_weeks >= 10 else 1
        milestone_interval_weeks = max(2, int(round(max(1, total_weeks - buffer_weeks) / 4.0)))
        domain_minimum_weeks = DOMAIN_MINIMUM_WEEKS.get(wave_domain, 8)

        goal_details = {
            "title": cls._build_title(session.goal_text, wave_domain),
            "description": cls._build_description(slot_profile, wave_domain, end_date.isoformat()),
            "why": cls._build_why(slot_profile, session.goal_text),
            "measurable_target": cls._build_measurable_target(slot_profile, wave_domain, end_date.isoformat()),
            "priority": _coerce_priority(cls._slot_value(slot_map.get("priority"))),
        }

        timeline = {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "total_weeks": total_weeks,
            "buffer_weeks": buffer_weeks,
            "milestone_interval_weeks": milestone_interval_weeks,
            "feasibility_status": "feasible" if total_weeks >= domain_minimum_weeks else "infeasible",
            "domain_minimum_weeks": domain_minimum_weeks,
        }

        return {
            "raw_goal": session.goal_text.strip(),
            "slot_profile": slot_profile,
            "goal_details": goal_details,
            "timeline": timeline,
        }

    @staticmethod
    def _required_keys_by_domain(wave_domain: str) -> list[str]:
        if wave_domain == WAVE4_DOMAIN_RUNNING_ENDURANCE:
            return [
                "current_fitness_baseline",
                "running_experience",
                "weekly_training_days",
                "daily_session_minutes",
                "injury_constraints",
                "equipment_and_location",
                "motivation_driver",
            ]
        if wave_domain == WAVE4_DOMAIN_FINANCE:
            return [
                "savings_target",
                "target_date",
                "monthly_income",
                "monthly_fixed_expenses",
                "current_savings",
                "existing_debt",
                "savings_purpose",
            ]
        if wave_domain == WAVE4_DOMAIN_SKILL_ACQUISITION:
            return [
                "current_skill_level",
                "has_required_equipment",
                "preferred_style_or_genre",
                "daily_practice_minutes",
                "goal_milestone_event",
                "learning_method",
            ]
        return [
            "current_role",
            "target_role",
            "time_in_current_role",
            "target_timeline",
            "manager_feedback_on_gaps",
            "available_opportunities",
        ]

    @staticmethod
    def _has_value(state: GIESlotState | None) -> bool:
        if not state:
            return False
        return state.status in {GIESlotState.STATUS_FILLED, GIESlotState.STATUS_LOCKED} and state.value not in (None, "")

    @staticmethod
    def _slot_value(state: GIESlotState | None):
        return state.value if state else None

    @classmethod
    def _resolve_target_date(cls, *, slot_map: dict[str, GIESlotState], wave_domain: str, fallback):
        domain_target_key = "target_date" if wave_domain == WAVE4_DOMAIN_FINANCE else "timeline_target_date"
        candidate = cls._slot_value(slot_map.get(domain_target_key))
        if not candidate:
            candidate = cls._slot_value(slot_map.get("timeline_target_date"))
        if not candidate:
            candidate = cls._slot_value(slot_map.get("target_date"))
        date_value = _iso_date_or_default(candidate, fallback)
        try:
            return timezone.datetime.strptime(date_value, "%Y-%m-%d").date()
        except ValueError:
            return fallback

    @staticmethod
    def _build_title(raw_goal: str, wave_domain: str) -> str:
        trimmed = (raw_goal or "").strip()
        if trimmed:
            return trimmed[:255]
        fallback = {
            WAVE4_DOMAIN_RUNNING_ENDURANCE: "Running Endurance Goal",
            WAVE4_DOMAIN_FINANCE: "Financial Savings Goal",
            WAVE4_DOMAIN_SKILL_ACQUISITION: "Skill Acquisition Goal",
            WAVE4_DOMAIN_CAREER: "Career Growth Goal",
        }
        return fallback.get(wave_domain, "Goal")

    @staticmethod
    def _build_description(slot_profile: dict, wave_domain: str, target_date: str) -> str:
        if wave_domain == WAVE4_DOMAIN_RUNNING_ENDURANCE:
            return (
                f"Train {slot_profile.get('weekly_training_days')} days/week for "
                f"{slot_profile.get('daily_session_minutes')} minutes to reach your running milestone by {target_date}."
            )
        if wave_domain == WAVE4_DOMAIN_FINANCE:
            return (
                f"Build savings to {slot_profile.get('savings_target')} by {target_date} "
                f"while balancing monthly income, expenses, and debt obligations."
            )
        if wave_domain == WAVE4_DOMAIN_SKILL_ACQUISITION:
            return (
                f"Practice {slot_profile.get('daily_practice_minutes')} minutes daily using "
                f"{slot_profile.get('learning_method')} to hit the milestone event by {target_date}."
            )
        return (
            f"Transition from {slot_profile.get('current_role')} to {slot_profile.get('target_role')} "
            f"within the target timeline while closing identified gaps."
        )

    @staticmethod
    def _build_why(slot_profile: dict, raw_goal: str) -> str:
        if isinstance(slot_profile.get("motivation_driver"), str) and slot_profile.get("motivation_driver"):
            return str(slot_profile["motivation_driver"])
        if isinstance(slot_profile.get("savings_purpose"), str) and slot_profile.get("savings_purpose"):
            return str(slot_profile["savings_purpose"])
        return (raw_goal or "").strip()[:500]

    @staticmethod
    def _build_measurable_target(slot_profile: dict, wave_domain: str, target_date: str) -> str:
        if wave_domain == WAVE4_DOMAIN_FINANCE:
            return f"Reach savings target of {slot_profile.get('savings_target')} by {target_date}."
        if wave_domain == WAVE4_DOMAIN_RUNNING_ENDURANCE:
            return f"Complete running milestone by {target_date}."
        if wave_domain == WAVE4_DOMAIN_SKILL_ACQUISITION:
            return f"Deliver {slot_profile.get('goal_milestone_event')} by {target_date}."
        return f"Reach target role by {target_date}."
