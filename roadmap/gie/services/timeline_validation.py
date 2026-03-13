from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

from gie.models import GIESession, GIESlotState

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

    BASELINE_DAYS_BY_DOMAIN = {
        GIESession.DOMAIN_CAREER: 300,
        GIESession.DOMAIN_HEALTH: 240,
        GIESession.DOMAIN_FINANCIAL: 180,
        GIESession.DOMAIN_LEARNING: 210,
        GIESession.DOMAIN_PERSONAL: 150,
        GIESession.DOMAIN_BUSINESS: 270,
        GIESession.DOMAIN_OTHER: 180,
    }

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

        target_date = cls._parse_iso_date(timeline_value)
        if not target_date:
            return None

        today = timezone.localdate()
        stated_timeline_days = max(1, (target_date - today).days)
        estimated_timeline_days = cls._estimate_timeline_days(
            session=session,
            slot_states_by_key=slot_states_by_key,
            health_profile=health_profile,
        )
        impact_percent = round(min(100.0, (stated_timeline_days / max(1, estimated_timeline_days)) * 100.0), 1)
        verdict = "realistic" if impact_percent >= 85.0 else "unrealistic"
        projected_full_goal_completion_date = (today + timedelta(days=estimated_timeline_days)).isoformat()

        return TimelineValidationResult(
            verdict=verdict,
            achievable_sub_goal=cls._build_sub_goal_text(
                session=session,
                slot_states_by_key=slot_states_by_key,
                stated_timeline_days=stated_timeline_days,
                estimated_timeline_days=estimated_timeline_days,
                impact_percent=impact_percent,
            ),
            projected_full_goal_completion_date=projected_full_goal_completion_date,
            impact_percent=impact_percent,
            stated_timeline_days=stated_timeline_days,
            estimated_timeline_days=estimated_timeline_days,
        )

    @classmethod
    def _estimate_timeline_days(cls, *, session: GIESession, slot_states_by_key: dict[str, GIESlotState], health_profile) -> int:
        baseline = cls.BASELINE_DAYS_BY_DOMAIN.get(session.goal_domain, cls.BASELINE_DAYS_BY_DOMAIN[GIESession.DOMAIN_OTHER])
        effort_multiplier = cls._effort_multiplier(slot_states_by_key)
        health_multiplier = cls._health_multiplier(session.goal_domain, health_profile)
        estimate = int(round(baseline * effort_multiplier * health_multiplier))
        return max(30, estimate)

    @staticmethod
    def _effort_multiplier(slot_states_by_key: dict[str, GIESlotState]) -> float:
        effort_candidates = []
        for key in (
            "weekly_effort_hours",
            "weekly_commitment_hours",
            "weekly_study_hours",
            "weekly_execution_hours",
        ):
            state = slot_states_by_key.get(key)
            if state and isinstance(state.value, (int, float)):
                effort_candidates.append(float(state.value))

        availability_state = slot_states_by_key.get("weekly_availability_days")
        if availability_state and isinstance(availability_state.value, (int, float)):
            effort_candidates.append(float(availability_state.value) * 1.5)
        training_days_state = slot_states_by_key.get("weekly_training_days")
        if training_days_state and isinstance(training_days_state.value, (int, float)):
            effort_candidates.append(float(training_days_state.value) * 1.5)

        weekly_effort = max(effort_candidates) if effort_candidates else 4.0
        if weekly_effort < 2:
            return 1.35
        if weekly_effort < 4:
            return 1.15
        if weekly_effort <= 7:
            return 1.0
        return 0.9

    @staticmethod
    def _health_multiplier(goal_domain: str, health_profile) -> float:
        if not health_profile:
            return 1.0

        multiplier = 1.0
        stress_level = getattr(health_profile, "stress_level", "")
        if stress_level == "high":
            multiplier += 0.2
        elif stress_level == "burnout":
            multiplier += 0.35

        sleep_pattern = getattr(health_profile, "sleep_pattern", "")
        if sleep_pattern == "irregular":
            multiplier += 0.1
        elif sleep_pattern == "shift_based":
            multiplier += 0.15

        willpower = getattr(health_profile, "willpower_level", "")
        if willpower == "low":
            multiplier += 0.12
        elif willpower == "high":
            multiplier -= 0.05

        conditions = getattr(health_profile, "conditions", []) or []
        if conditions:
            multiplier += 0.12
        if getattr(health_profile, "on_medication", False):
            multiplier += 0.08

        if goal_domain == GIESession.DOMAIN_HEALTH:
            fitness = getattr(health_profile, "fitness_level", "")
            if fitness == "sedentary":
                multiplier += 0.25
            elif fitness == "light":
                multiplier += 0.15
            elif fitness == "athletic":
                multiplier -= 0.1

        return max(0.7, min(2.0, multiplier))

    @classmethod
    def _build_sub_goal_text(
        cls,
        *,
        session: GIESession,
        slot_states_by_key: dict[str, GIESlotState],
        stated_timeline_days: int,
        estimated_timeline_days: int,
        impact_percent: float,
    ) -> str:
        coverage = max(5, min(100, int(round(impact_percent))))
        if session.goal_domain == GIESession.DOMAIN_FINANCIAL:
            target_state = slot_states_by_key.get("target_amount") or slot_states_by_key.get("savings_target")
            saved_state = slot_states_by_key.get("current_saved_amount") or slot_states_by_key.get("current_savings")
            monthly_state = slot_states_by_key.get("monthly_saving_capacity")
            inferred_capacity = None
            if monthly_state is None:
                income_state = slot_states_by_key.get("monthly_income")
                fixed_state = slot_states_by_key.get("monthly_fixed_expenses")
                debt_state = slot_states_by_key.get("existing_debt")
                if (
                    income_state
                    and fixed_state
                    and debt_state
                    and isinstance(income_state.value, (int, float))
                    and isinstance(fixed_state.value, (int, float))
                    and isinstance(debt_state.value, (int, float))
                ):
                    inferred_capacity = max(
                        0.0,
                        float(income_state.value) - float(fixed_state.value) - float(debt_state.value),
                    )
            if (
                target_state
                and saved_state
                and isinstance(target_state.value, (int, float))
                and isinstance(saved_state.value, (int, float))
                and (
                    (monthly_state and isinstance(monthly_state.value, (int, float)))
                    or isinstance(inferred_capacity, (int, float))
                )
            ):
                months = max(1, int(round(stated_timeline_days / 30.0)))
                monthly_capacity = (
                    float(monthly_state.value)
                    if monthly_state and isinstance(monthly_state.value, (int, float))
                    else float(inferred_capacity)
                )
                achievable = float(saved_state.value) + monthly_capacity * months
                capped = min(float(target_state.value), achievable)
                return f"Reach about {capped:.0f} toward your savings target in this period."

        months_label = max(1, int(round(stated_timeline_days / 30.0)))
        full_months = max(1, int(round(estimated_timeline_days / 30.0)))
        return f"Complete roughly {coverage}% of the full goal in ~{months_label} month(s), then finish in ~{full_months} month(s)."

    @staticmethod
    def _parse_iso_date(value) -> timezone.datetime.date | None:
        if not isinstance(value, str):
            return None
        text = value.strip()
        if not text:
            return None
        try:
            return timezone.datetime.strptime(text, "%Y-%m-%d").date()
        except ValueError:
            return None
