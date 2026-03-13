from __future__ import annotations

from datetime import timedelta
from math import ceil

from django.utils import timezone

from gie.models import GIESession, GIESlotState
from gie.services.dynamic_schema import (
    WAVE4_DOMAIN_CAREER,
    WAVE4_DOMAIN_FINANCE,
    WAVE4_DOMAIN_RUNNING_ENDURANCE,
    WAVE4_DOMAIN_SKILL_ACQUISITION,
    map_session_domain_to_wave4_domain,
)

TIMELINE_FEASIBILITY_SLOT_KEY = "__timeline_feasibility"


class GIETimelineFeasibilityService:
    """Deterministic feasibility guardrail checks (TASK-B127)."""

    @classmethod
    def domain_minimum_weeks(cls, *, session: GIESession, unified_context: dict | None = None) -> int:
        context = unified_context or {}
        wave_domain = map_session_domain_to_wave4_domain(session.goal_domain, session.goal_text)
        goal_text = (session.goal_text or "").lower()

        if wave_domain == WAVE4_DOMAIN_RUNNING_ENDURANCE:
            if "5k" in goal_text or "5 k" in goal_text:
                return 6
            return 12

        if wave_domain == WAVE4_DOMAIN_SKILL_ACQUISITION:
            if "language" in goal_text and any(token in goal_text for token in ("fluency", "fluent")):
                return 52
            return 8

        if wave_domain == WAVE4_DOMAIN_CAREER:
            return 26

        if wave_domain == WAVE4_DOMAIN_FINANCE:
            # Finance duration is validated primarily by feasibility math.
            return max(4, int(context.get("timeline", {}).get("domain_minimum_weeks", 4)))

        return 8

    @classmethod
    def evaluate(cls, *, session: GIESession, slot_states: list[GIESlotState], unified_context: dict) -> dict:
        slot_map = {state.slot_key: state for state in slot_states}
        timeline = unified_context.get("timeline", {})

        start_date = cls._parse_iso_date(timeline.get("start_date")) or timezone.localdate()
        end_date = cls._parse_iso_date(timeline.get("end_date"))
        if not end_date:
            return {
                "feasible": False,
                "reason": "A target date is required for timeline feasibility validation.",
                "options": [
                    {
                        "label": "Set target date",
                        "adjusted_date": (start_date + timedelta(weeks=8)).isoformat(),
                        "description": "Provide a concrete target date before finalizing.",
                    }
                ],
            }

        total_weeks = max(1, int(ceil(max(1, (end_date - start_date).days) / 7.0)))
        minimum_weeks = cls.domain_minimum_weeks(session=session, unified_context=unified_context)

        if total_weeks < minimum_weeks:
            return {
                "feasible": False,
                "reason": f"Requested timeline is below domain minimum ({minimum_weeks} weeks).",
                "options": [
                    {
                        "label": "Extend to minimum",
                        "adjusted_date": (start_date + timedelta(weeks=minimum_weeks)).isoformat(),
                        "description": f"Use at least {minimum_weeks} weeks for safer execution.",
                    },
                    {
                        "label": "Reduce scope",
                        "adjusted_date": (start_date + timedelta(weeks=max(6, minimum_weeks - 4))).isoformat(),
                        "description": "Choose a smaller milestone aligned with current constraints.",
                    },
                ],
            }

        finance_result = cls._evaluate_finance_math(session=session, slot_map=slot_map, start_date=start_date, end_date=end_date)
        if finance_result is not None:
            return finance_result

        buffer_weeks = 2 if total_weeks >= 10 else 1
        if buffer_weeks not in (1, 2):
            return {
                "feasible": False,
                "reason": "Buffer weeks must be between 1 and 2.",
                "options": [
                    {
                        "label": "Apply 2-week buffer",
                        "adjusted_date": (end_date + timedelta(weeks=2)).isoformat(),
                        "description": "Reserve contingency for disruptions and recovery.",
                    }
                ],
            }

        executable_weeks = max(1, total_weeks - buffer_weeks)
        milestone_interval_weeks = int(timeline.get("milestone_interval_weeks") or 2)
        if milestone_interval_weeks < 2:
            return {
                "feasible": False,
                "reason": "Milestone spacing must be at least 2 weeks.",
                "options": [
                    {
                        "label": "Increase milestone spacing",
                        "adjusted_date": end_date.isoformat(),
                        "description": "Space milestones every 2+ weeks.",
                    }
                ],
            }

        milestone_count = max(1, int(executable_weeks // milestone_interval_weeks))
        if milestone_count > 1 and (executable_weeks / milestone_count) < 2:
            return {
                "feasible": False,
                "reason": "Milestone density is too high; intervals must be at least 2 weeks.",
                "options": [
                    {
                        "label": "Reduce milestone count",
                        "adjusted_date": end_date.isoformat(),
                        "description": "Consolidate milestones to maintain 2-week spacing.",
                    }
                ],
            }

        return {
            "feasible": True,
            "buffer_weeks": buffer_weeks,
            "milestone_count": milestone_count,
        }

    @classmethod
    def _evaluate_finance_math(
        cls,
        *,
        session: GIESession,
        slot_map: dict[str, GIESlotState],
        start_date,
        end_date,
    ) -> dict | None:
        wave_domain = map_session_domain_to_wave4_domain(session.goal_domain, session.goal_text)
        if wave_domain != WAVE4_DOMAIN_FINANCE:
            return None

        savings_target = cls._coerce_number(slot_map.get("savings_target"))
        current_savings = cls._coerce_number(slot_map.get("current_savings"))
        monthly_income = cls._coerce_number(slot_map.get("monthly_income"))
        monthly_fixed_expenses = cls._coerce_number(slot_map.get("monthly_fixed_expenses"))
        debt_obligations = cls._coerce_number(slot_map.get("existing_debt"))

        if None in (savings_target, current_savings, monthly_income, monthly_fixed_expenses, debt_obligations):
            return {
                "feasible": False,
                "reason": "Finance feasibility requires savings, income, expense, and debt inputs.",
                "options": [
                    {
                        "label": "Fill missing finance slots",
                        "adjusted_date": end_date.isoformat(),
                        "description": "Provide all required financial inputs before finalizing.",
                    }
                ],
            }

        months_to_target = max(1, int(ceil(max(1, (end_date - start_date).days) / 30.0)))
        required_monthly_saving = max(0.0, (savings_target - current_savings) / months_to_target)
        available_surplus = monthly_income - monthly_fixed_expenses - debt_obligations

        if required_monthly_saving > available_surplus:
            months_needed = max(1, int(ceil((savings_target - current_savings) / max(1.0, available_surplus))))
            return {
                "feasible": False,
                "reason": "Required monthly saving is above available monthly surplus.",
                "options": [
                    {
                        "label": "Extend date",
                        "adjusted_date": (start_date + timedelta(days=months_needed * 30)).isoformat(),
                        "description": "Extend timeline to align required saving with available surplus.",
                    },
                    {
                        "label": "Reduce target",
                        "adjusted_date": end_date.isoformat(),
                        "description": "Lower savings target or increase surplus to fit timeline.",
                    },
                ],
            }

        return None

    @staticmethod
    def _coerce_number(state: GIESlotState | None) -> float | None:
        if not state:
            return None
        value = state.value
        if isinstance(value, (int, float)):
            return float(value)
        return None

    @staticmethod
    def _parse_iso_date(value):
        if not isinstance(value, str):
            return None
        try:
            return timezone.datetime.strptime(value.strip(), "%Y-%m-%d").date()
        except ValueError:
            return None
