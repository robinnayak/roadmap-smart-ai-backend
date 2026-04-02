from __future__ import annotations

import re
from datetime import timedelta

from django.utils import timezone

from gie.models import GIESession, GIESlotState
from gie.services.dynamic_schema import (
    WAVE4_DOMAIN_CAREER,
    WAVE4_DOMAIN_FINANCE,
    WAVE4_DOMAIN_NUTRITION,
    WAVE4_DOMAIN_RUNNING_ENDURANCE,
    WAVE4_DOMAIN_SKILL_ACQUISITION,
    WAVE4_DOMAIN_WELLNESS,
    map_session_domain_to_wave4_domain,
)

DOMAIN_MINIMUM_WEEKS = {
    WAVE4_DOMAIN_RUNNING_ENDURANCE: 12,
    WAVE4_DOMAIN_NUTRITION: 6,
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
            "title": cls._build_title(
                raw_goal=session.goal_text,
                wave_domain=wave_domain,
                slot_profile=slot_profile,
                target_date=end_date.isoformat(),
            ),
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

        task_generation_context = cls._build_task_generation_context(
            slot_profile=slot_profile,
            wave_domain=wave_domain,
        )

        return {
            "raw_goal": session.goal_text.strip(),
            "slot_profile": slot_profile,
            "goal_details": goal_details,
            "timeline": timeline,
            "task_generation_context": task_generation_context,
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
        if wave_domain == WAVE4_DOMAIN_NUTRITION:
            return [
                "current_nutrition_baseline",
                "meal_prep_days_per_week",
                "meals_to_prepare_per_day",
                "protein_goal_grams_per_day",
                "dietary_constraints",
                "prep_time_per_day_minutes",
                "motivation_driver",
            ]
        if wave_domain == WAVE4_DOMAIN_WELLNESS:
            return [
                "current_wellness_baseline",
                "primary_challenge",
                "daily_time_available",
                "existing_practices",
                "trigger_context",
                "motivation_driver",
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
    def _build_title(*, raw_goal: str, wave_domain: str, slot_profile: dict, target_date: str) -> str:
        trimmed = (raw_goal or "").strip()
        normalized_phrase = GIEUnifiedContextService._normalize_goal_phrase(trimmed)
        if normalized_phrase:
            if wave_domain == WAVE4_DOMAIN_SKILL_ACQUISITION:
                focus = GIEUnifiedContextService._extract_goal_focus(normalized_phrase)
                if focus:
                    return f"Build {focus.title()} Skills Through Consistent Practice by {target_date}"[:255]
                return f"Build Practical Skills Through Consistent Practice by {target_date}"[:255]
            if wave_domain == WAVE4_DOMAIN_RUNNING_ENDURANCE:
                return f"Build Running Endurance Consistently by {target_date}"[:255]
            if wave_domain == WAVE4_DOMAIN_NUTRITION:
                return f"Build a Consistent High-Protein Meal Prep Routine by {target_date}"[:255]
            if wave_domain == WAVE4_DOMAIN_FINANCE:
                return f"Reach Savings Target with a Structured Plan by {target_date}"[:255]
            if wave_domain == WAVE4_DOMAIN_CAREER:
                target_role = GIEUnifiedContextService._as_text(slot_profile.get("target_role"), fallback="")
                if target_role:
                    return f"Progress into {target_role} with a Structured Growth Plan by {target_date}"[:255]
                return f"Advance Career Growth Through Structured Weekly Execution by {target_date}"[:255]
            return f"{normalized_phrase[:1].upper() + normalized_phrase[1:]} by {target_date}"[:255]

        target_role = GIEUnifiedContextService._as_text(slot_profile.get("target_role"), fallback="")
        if target_role and wave_domain == WAVE4_DOMAIN_CAREER:
            return f"Progress into {target_role} with a Structured Growth Plan by {target_date}"[:255]

        fallback = {
            WAVE4_DOMAIN_RUNNING_ENDURANCE: "Running Endurance Goal",
            WAVE4_DOMAIN_NUTRITION: "Nutrition Consistency Goal",
            WAVE4_DOMAIN_FINANCE: "Financial Savings Goal",
            WAVE4_DOMAIN_SKILL_ACQUISITION: "Skill Acquisition Goal",
            WAVE4_DOMAIN_CAREER: "Career Growth Goal",
        }
        return fallback.get(wave_domain, "Goal")

    @staticmethod
    def _build_description(slot_profile: dict, wave_domain: str, target_date: str) -> str:
        if wave_domain == WAVE4_DOMAIN_RUNNING_ENDURANCE:
            weekly_training_days = GIEUnifiedContextService._as_text(slot_profile.get("weekly_training_days"), fallback="3")
            daily_session_minutes = GIEUnifiedContextService._as_text(slot_profile.get("daily_session_minutes"), fallback="30")
            return (
                f"Train {weekly_training_days} days/week for "
                f"{daily_session_minutes} minutes to reach your running milestone by {target_date}."
            )
        if wave_domain == WAVE4_DOMAIN_FINANCE:
            savings_target = GIEUnifiedContextService._as_text(slot_profile.get("savings_target"), fallback="your target amount")
            return (
                f"Build savings to {savings_target} by {target_date} "
                f"while balancing monthly income, expenses, and debt obligations."
            )
        if wave_domain == WAVE4_DOMAIN_NUTRITION:
            meals_to_prepare_per_day = GIEUnifiedContextService._as_text(slot_profile.get("meals_to_prepare_per_day"), fallback="2")
            meal_prep_days_per_week = GIEUnifiedContextService._as_text(slot_profile.get("meal_prep_days_per_week"), fallback="4")
            protein_goal_grams_per_day = GIEUnifiedContextService._as_text(slot_profile.get("protein_goal_grams_per_day"), fallback="100")
            dietary_constraints = GIEUnifiedContextService._as_text(slot_profile.get("dietary_constraints"), fallback="personal dietary constraints")
            return (
                f"Prep {meals_to_prepare_per_day} high-protein meals per day on "
                f"{meal_prep_days_per_week} days/week, targeting "
                f"{protein_goal_grams_per_day}g protein daily while respecting "
                f"{dietary_constraints} by {target_date}."
            )
        if wave_domain == WAVE4_DOMAIN_SKILL_ACQUISITION:
            daily_practice_minutes = GIEUnifiedContextService._as_text(slot_profile.get("daily_practice_minutes"), fallback="30")
            learning_method = GIEUnifiedContextService._as_text(slot_profile.get("learning_method"), fallback="a consistent learning method")
            goal_milestone_event = GIEUnifiedContextService._as_text(slot_profile.get("goal_milestone_event"), fallback="a clear milestone event")
            return (
                f"Practice {daily_practice_minutes} minutes daily using "
                f"{learning_method} to hit {goal_milestone_event} by {target_date}."
            )
        current_role = GIEUnifiedContextService._as_text(slot_profile.get("current_role"), fallback="your current role")
        target_role = GIEUnifiedContextService._as_text(slot_profile.get("target_role"), fallback="your target role")
        return (
            f"Transition from {current_role} to {target_role} "
            f"within the target timeline while closing identified gaps."
        )

    @staticmethod
    def _build_why(slot_profile: dict, raw_goal: str) -> str:
        if isinstance(slot_profile.get("motivation_driver"), str) and slot_profile.get("motivation_driver"):
            return str(slot_profile["motivation_driver"])
        if isinstance(slot_profile.get("savings_purpose"), str) and slot_profile.get("savings_purpose"):
            return str(slot_profile["savings_purpose"])
        normalized_goal = GIEUnifiedContextService._normalize_goal_phrase(raw_goal or "")
        focus = GIEUnifiedContextService._extract_goal_focus(normalized_goal)
        if focus:
            return f"I want this goal because building {focus} consistently will improve confidence, discipline, and long-term progress."
        if normalized_goal:
            return (
                f"I want this goal because {normalized_goal} will improve my consistency and create meaningful "
                f"long-term progress."
            )[:500]
        return "I want this goal because consistent execution will improve my long-term quality of life."

    @staticmethod
    def _build_measurable_target(slot_profile: dict, wave_domain: str, target_date: str) -> str:
        if wave_domain == WAVE4_DOMAIN_FINANCE:
            savings_target = GIEUnifiedContextService._as_text(slot_profile.get("savings_target"), fallback="your target amount")
            return f"Reach savings target of {savings_target} by {target_date}."
        if wave_domain == WAVE4_DOMAIN_RUNNING_ENDURANCE:
            return f"Complete running milestone by {target_date}."
        if wave_domain == WAVE4_DOMAIN_NUTRITION:
            protein_goal_grams_per_day = GIEUnifiedContextService._as_text(slot_profile.get("protein_goal_grams_per_day"), fallback="100")
            meal_prep_days_per_week = GIEUnifiedContextService._as_text(slot_profile.get("meal_prep_days_per_week"), fallback="4")
            return (
                f"Hit {protein_goal_grams_per_day}g protein daily and maintain "
                f"{meal_prep_days_per_week} prep days/week by {target_date}."
            )
        if wave_domain == WAVE4_DOMAIN_SKILL_ACQUISITION:
            goal_milestone_event = GIEUnifiedContextService._as_text(slot_profile.get("goal_milestone_event"), fallback="a meaningful milestone")
            return f"Deliver {goal_milestone_event} by {target_date}."
        return f"Reach target role by {target_date}."

    @classmethod
    def _build_task_generation_context(cls, *, slot_profile: dict, wave_domain: str) -> dict:
        return {
            "available_daily_minutes": cls._resolve_available_daily_minutes(slot_profile),
            "user_strengths": cls._resolve_user_strengths(slot_profile=slot_profile, wave_domain=wave_domain),
            "user_blockers": cls._resolve_user_blockers(slot_profile=slot_profile, wave_domain=wave_domain),
            "motivation_style": cls._resolve_motivation_style(slot_profile=slot_profile),
        }

    @classmethod
    def _resolve_available_daily_minutes(cls, slot_profile: dict) -> int:
        for key in ("daily_session_minutes", "daily_practice_minutes", "prep_time_per_day_minutes"):
            value = slot_profile.get(key)
            if isinstance(value, (int, float)):
                return max(0, int(round(float(value))))
            if isinstance(value, str) and value.strip().isdigit():
                return max(0, int(value.strip()))
        return 60

    @classmethod
    def _resolve_user_strengths(cls, *, slot_profile: dict, wave_domain: str) -> list[str]:
        strengths: list[str] = []
        for key in ("available_opportunities", "running_experience", "current_skill_level", "learning_method"):
            value = cls._as_text(slot_profile.get(key), fallback="")
            if value:
                strengths.append(value)

        if wave_domain == WAVE4_DOMAIN_FINANCE and cls._as_text(slot_profile.get("current_savings"), fallback=""):
            strengths.append(f"Current savings: {cls._as_text(slot_profile.get('current_savings'), fallback='0')}")

        if wave_domain == WAVE4_DOMAIN_CAREER and cls._as_text(slot_profile.get("current_role"), fallback=""):
            strengths.append(f"Current role: {cls._as_text(slot_profile.get('current_role'), fallback='')}")

        return strengths

    @classmethod
    def _resolve_user_blockers(cls, *, slot_profile: dict, wave_domain: str) -> list[str]:
        blockers: list[str] = []
        for key in ("injury_constraints", "dietary_constraints", "manager_feedback_on_gaps"):
            value = cls._as_text(slot_profile.get(key), fallback="")
            if value:
                blockers.append(value)

        if wave_domain == WAVE4_DOMAIN_FINANCE and cls._as_text(slot_profile.get("existing_debt"), fallback=""):
            blockers.append(f"Existing debt: {cls._as_text(slot_profile.get('existing_debt'), fallback='0')}")

        return blockers

    @classmethod
    def _resolve_motivation_style(cls, *, slot_profile: dict) -> str:
        motivation_driver = cls._as_text(
            slot_profile.get("motivation_driver") or slot_profile.get("savings_purpose"),
            fallback="",
        ).lower()
        if not motivation_driver:
            return "intrinsic"
        if any(token in motivation_driver for token in ("deadline", "date", "save", "amount", "race", "event")):
            return "outcome-driven"
        if any(token in motivation_driver for token in ("accountability", "mentor", "manager", "coach")):
            return "accountability-driven"
        return "intrinsic"

    @staticmethod
    def _as_text(value, *, fallback: str) -> str:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)):
            if isinstance(value, float) and value.is_integer():
                return str(int(value))
            return str(value)
        return fallback

    @staticmethod
    def _normalize_goal_phrase(raw_goal: str) -> str:
        text = re.sub(r"\s+", " ", (raw_goal or "").strip())
        text = text.rstrip(".!?")
        lower = text.lower()
        prefixes = (
            "i want to ",
            "i want ",
            "my goal is to ",
            "my goal is ",
            "goal: ",
        )
        for prefix in prefixes:
            if lower.startswith(prefix):
                text = text[len(prefix):].strip()
                break
        return text

    @staticmethod
    def _extract_goal_focus(goal_phrase: str) -> str:
        if not goal_phrase:
            return ""
        lowered = goal_phrase.lower()
        for prefix in ("learn ", "practice ", "build ", "improve ", "develop ", "master "):
            if lowered.startswith(prefix):
                return goal_phrase[len(prefix):].strip()
        return goal_phrase.strip()
