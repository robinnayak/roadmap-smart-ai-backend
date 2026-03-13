from __future__ import annotations

from dataclasses import dataclass

from gie.models import GIESession, GIESlotState
from gie.services.unified_context import GIEUnifiedContextService


@dataclass(frozen=True)
class RankedHabitSuggestion:
    habit_name: str
    rationale: str
    impact_score: float
    effort_score: float

    @property
    def impact_to_effort(self) -> float:
        return round(self.impact_score / max(0.1, self.effort_score), 3)

    def as_dict(self) -> dict:
        return {
            "habit_name": self.habit_name,
            "rationale": self.rationale,
            "impact_score": round(self.impact_score, 2),
            "effort_score": round(self.effort_score, 2),
            "impact_to_effort": self.impact_to_effort,
        }


class GIEHabitRankingService:
    """Deterministic ranking for top habit suggestions in a goal session."""

    DOMAIN_HABITS = {
        GIESession.DOMAIN_HEALTH: [
            ("Train on scheduled days", 9.4, 5.0),
            ("Sleep 7+ hours before training days", 8.7, 3.0),
            ("Track recovery and soreness daily", 7.9, 2.4),
            ("Hydrate before every workout", 7.2, 1.8),
        ],
        GIESession.DOMAIN_FINANCIAL: [
            ("Automate monthly transfer to goal fund", 9.6, 2.5),
            ("Log every discretionary spend daily", 8.6, 3.1),
            ("Weekly spending review with one cut action", 8.1, 3.3),
            ("Use a 24-hour rule for non-essential purchases", 7.5, 2.1),
        ],
        GIESession.DOMAIN_CAREER: [
            ("Ship one portfolio-proof task each week", 9.1, 4.2),
            ("Daily 45-minute deep-work block", 8.8, 3.6),
            ("Weekly feedback request from mentor/peer", 7.8, 2.2),
            ("Track outcomes and wins every Friday", 7.1, 1.8),
        ],
        GIESession.DOMAIN_LEARNING: [
            ("Study on fixed weekly slots", 9.2, 3.8),
            ("Build one practice artifact per week", 8.9, 4.1),
            ("Active recall session after each study block", 8.2, 2.4),
            ("Weekly review and weak-topic backlog", 7.3, 2.0),
        ],
        GIESession.DOMAIN_PERSONAL: [
            ("10-minute daily reflection", 8.4, 1.9),
            ("Weekly planning checkpoint", 8.1, 2.1),
            ("Daily non-negotiable micro-action", 8.8, 2.7),
            ("Weekly accountability message", 7.2, 1.7),
        ],
        GIESession.DOMAIN_BUSINESS: [
            ("Daily pipeline or distribution action", 9.3, 3.5),
            ("Weekly metric review and correction", 8.7, 2.8),
            ("Block deep execution slots three times weekly", 8.5, 3.9),
            ("Customer feedback capture after each call", 7.9, 2.3),
        ],
        GIESession.DOMAIN_OTHER: [
            ("Daily 20-minute focused action block", 8.5, 2.5),
            ("Weekly progress review and next-step lock", 8.0, 2.2),
            ("Track one leading indicator daily", 7.6, 2.0),
            ("Define tomorrow's first action nightly", 7.1, 1.6),
        ],
    }

    @classmethod
    def rank(
        cls,
        *,
        session: GIESession,
        slot_states: list[GIESlotState],
        health_profile,
    ) -> list[dict]:
        state_by_key = {state.slot_key: state for state in slot_states}
        unified_context = GIEUnifiedContextService.build(session=session, slot_states=slot_states)
        candidates = cls.DOMAIN_HABITS.get(session.goal_domain, cls.DOMAIN_HABITS[GIESession.DOMAIN_OTHER])
        adjusted: list[RankedHabitSuggestion] = []
        weekly_capacity = cls._weekly_capacity(state_by_key)

        for habit_name, base_impact, base_effort in candidates:
            impact = base_impact
            effort = base_effort

            if weekly_capacity < 3:
                effort += 0.9
                impact -= 0.3
            elif weekly_capacity > 6:
                effort -= 0.4
                impact += 0.2

            if health_profile and getattr(health_profile, "stress_level", "") in {"high", "burnout"}:
                if "daily" in habit_name.lower():
                    effort += 0.6
                if "review" in habit_name.lower() or "reflection" in habit_name.lower():
                    impact += 0.2

            rationale = cls._rationale_for_habit(
                habit_name=habit_name,
                unified_context=unified_context,
            )
            adjusted.append(
                RankedHabitSuggestion(
                    habit_name=habit_name,
                    rationale=rationale,
                    impact_score=impact,
                    effort_score=max(1.0, effort),
                )
            )

        ranked = sorted(
            adjusted,
            key=lambda item: (item.impact_to_effort, item.impact_score, -item.effort_score),
            reverse=True,
        )
        return [item.as_dict() for item in ranked[:3]]

    @staticmethod
    def _weekly_capacity(state_by_key: dict[str, GIESlotState]) -> float:
        for key in (
            "weekly_effort_hours",
            "weekly_study_hours",
            "weekly_execution_hours",
            "weekly_commitment_hours",
        ):
            state = state_by_key.get(key)
            if state and isinstance(state.value, (int, float)):
                return float(state.value)
        availability = state_by_key.get("weekly_availability_days")
        if availability and isinstance(availability.value, (int, float)):
            return float(availability.value)
        return 4.0

    @staticmethod
    def _rationale_for_habit(*, habit_name: str, unified_context: dict) -> str:
        slot_profile = unified_context.get("slot_profile", {})
        timeline = unified_context.get("timeline", {})
        goal_details = unified_context.get("goal_details", {})
        raw_goal = str(unified_context.get("raw_goal") or "").strip()

        deadline = GIEHabitRankingService._as_string(timeline.get("end_date"), fallback="your target date")
        goal_reference = GIEHabitRankingService._as_string(
            goal_details.get("title") or goal_details.get("description") or raw_goal,
            fallback="your goal",
        )
        domain = GIEHabitRankingService._as_string(slot_profile.get("goal_domain"), fallback="goal").replace("_", " ")
        personal_reason = GIEHabitRankingService._personal_reason(slot_profile=slot_profile, goal_details=goal_details)
        habit_lower = habit_name.lower()

        if slot_profile.get("goal_domain") == "running_endurance":
            weekly_days = GIEHabitRankingService._as_number_phrase(slot_profile.get("weekly_training_days"), fallback="planned")
            session_minutes = GIEHabitRankingService._as_number_phrase(slot_profile.get("daily_session_minutes"), fallback="planned")
            motivation = GIEHabitRankingService._as_string(slot_profile.get("motivation_driver"), fallback=personal_reason)
            injuries = GIEHabitRankingService._as_string(slot_profile.get("injury_constraints"), fallback="no major constraints noted")
            if "hydrate" in habit_lower:
                return (
                    f"For {goal_reference}, this protects run quality on your {weekly_days}-day weekly plan and "
                    f"keeps your {session_minutes}-minute sessions consistent through {deadline}."
                )
            if "recovery" in habit_lower or "soreness" in habit_lower:
                return (
                    f"For {goal_reference}, daily recovery checks matter because your injury context is '{injuries}', "
                    f"and catching strain early preserves progress to {deadline}."
                )
            if "sleep" in habit_lower:
                return (
                    f"For {goal_reference}, sleep supports adaptation between sessions so your {weekly_days}-day training "
                    f"schedule stays sustainable through {deadline} and aligned with '{motivation}'."
                )
            return (
                f"For {goal_reference}, this keeps your {weekly_days}-day running rhythm stable and supports '{motivation}' "
                f"by building repeatable execution through {deadline}."
            )

        if slot_profile.get("goal_domain") == "finance":
            target = GIEHabitRankingService._as_number_phrase(slot_profile.get("savings_target"), fallback="your savings target")
            purpose = GIEHabitRankingService._as_string(slot_profile.get("savings_purpose"), fallback=personal_reason)
            income = GIEHabitRankingService._as_number_phrase(slot_profile.get("monthly_income"), fallback="your income")
            expenses = GIEHabitRankingService._as_number_phrase(slot_profile.get("monthly_fixed_expenses"), fallback="your fixed expenses")
            debt = GIEHabitRankingService._as_number_phrase(slot_profile.get("existing_debt"), fallback="your debt obligations")
            if "automate" in habit_lower or "transfer" in habit_lower:
                return (
                    f"For {goal_reference}, automating transfers protects progress toward {target} by {deadline} and "
                    f"turns '{purpose}' into a default action before discretionary spending."
                )
            if "spend" in habit_lower or "purchase" in habit_lower:
                return (
                    f"For {goal_reference}, controlling discretionary spending matters because income ({income}) minus "
                    f"fixed expenses ({expenses}) and debt ({debt}) must stay available to hit {target} by {deadline}."
                )
            return (
                f"For {goal_reference}, this habit converts your monthly cash-flow constraints into consistent savings "
                f"progress toward {target} by {deadline} for '{purpose}'."
            )

        if slot_profile.get("goal_domain") == "career":
            current_role = GIEHabitRankingService._as_string(slot_profile.get("current_role"), fallback="your current role")
            target_role = GIEHabitRankingService._as_string(slot_profile.get("target_role"), fallback="your target role")
            gap = GIEHabitRankingService._as_string(slot_profile.get("manager_feedback_on_gaps"), fallback=personal_reason)
            if "feedback" in habit_lower:
                return (
                    f"For {goal_reference}, structured feedback closes the '{gap}' gap faster so you can move from "
                    f"{current_role} to {target_role} by {deadline}."
                )
            if "portfolio" in habit_lower or "outcomes" in habit_lower:
                return (
                    f"For {goal_reference}, visible proof of outcomes is required to progress from {current_role} to "
                    f"{target_role}, and this habit builds that evidence before {deadline}."
                )
            return (
                f"For {goal_reference}, this targets your stated growth gap ('{gap}') and supports the move from "
                f"{current_role} to {target_role} by {deadline}."
            )

        if slot_profile.get("goal_domain") == "skill_acquisition":
            level = GIEHabitRankingService._as_string(slot_profile.get("current_skill_level"), fallback="current level")
            daily_minutes = GIEHabitRankingService._as_number_phrase(slot_profile.get("daily_practice_minutes"), fallback="planned")
            event_name = GIEHabitRankingService._as_string(slot_profile.get("goal_milestone_event"), fallback=goal_reference)
            method = GIEHabitRankingService._as_string(slot_profile.get("learning_method"), fallback=personal_reason)
            return (
                f"For {goal_reference}, this reinforces {method} at {daily_minutes} minutes per day from your current "
                f"'{level}' baseline so you can deliver '{event_name}' by {deadline}."
            )

        return (
            f"For your {domain} goal ({goal_reference}), this habit creates specific execution momentum toward {deadline} "
            f"because your profile points to '{personal_reason}'."
        )

    @staticmethod
    def _as_string(value, *, fallback: str) -> str:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)):
            return str(value)
        return fallback

    @staticmethod
    def _as_number_phrase(value, *, fallback: str) -> str:
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            return str(int(round(value)))
        return fallback

    @staticmethod
    def _personal_reason(*, slot_profile: dict, goal_details: dict) -> str:
        candidates = (
            slot_profile.get("motivation_driver"),
            slot_profile.get("savings_purpose"),
            slot_profile.get("manager_feedback_on_gaps"),
            slot_profile.get("learning_method"),
            slot_profile.get("injury_constraints"),
            goal_details.get("why"),
        )
        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return "the constraints and motivation you already confirmed"
