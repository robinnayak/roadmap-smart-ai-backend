from __future__ import annotations

from datetime import date, timedelta
from math import ceil

from django.utils import timezone


TIMELINE_BASELINE_DAYS_BY_DOMAIN = {
    "career": 300,
    "health": 240,
    "financial": 180,
    "learning": 210,
    "personal": 150,
    "business": 270,
    "other": 180,
}


def parse_iso_date(value) -> date | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return timezone.datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def coerce_number(value) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def timeline_effort_multiplier(slot_values: dict) -> float:
    effort_candidates = []
    for key in (
        "weekly_effort_hours",
        "weekly_commitment_hours",
        "weekly_study_hours",
        "weekly_execution_hours",
    ):
        value = coerce_number(slot_values.get(key))
        if value is not None:
            effort_candidates.append(value)

    availability_days = coerce_number(slot_values.get("weekly_availability_days"))
    if availability_days is not None:
        effort_candidates.append(availability_days * 1.5)

    training_days = coerce_number(slot_values.get("weekly_training_days"))
    if training_days is not None:
        effort_candidates.append(training_days * 1.5)

    weekly_effort = max(effort_candidates) if effort_candidates else 4.0
    if weekly_effort < 2:
        return 1.35
    if weekly_effort < 4:
        return 1.15
    if weekly_effort <= 7:
        return 1.0
    return 0.9


def timeline_health_multiplier(*, goal_domain: str, health_profile) -> float:
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

    if goal_domain == "health":
        fitness = getattr(health_profile, "fitness_level", "")
        if fitness == "sedentary":
            multiplier += 0.25
        elif fitness == "light":
            multiplier += 0.15
        elif fitness == "athletic":
            multiplier -= 0.1

    return max(0.7, min(2.0, multiplier))


def estimate_timeline_days(*, goal_domain: str, slot_values: dict, health_profile) -> int:
    baseline = TIMELINE_BASELINE_DAYS_BY_DOMAIN.get(
        goal_domain,
        TIMELINE_BASELINE_DAYS_BY_DOMAIN["other"],
    )
    estimate = int(
        round(
            baseline
            * timeline_effort_multiplier(slot_values)
            * timeline_health_multiplier(goal_domain=goal_domain, health_profile=health_profile)
        )
    )
    return max(30, estimate)


def build_achievable_sub_goal_text(
    *,
    goal_domain: str,
    slot_values: dict,
    stated_timeline_days: int,
    estimated_timeline_days: int,
    impact_percent: float,
) -> str:
    coverage = max(5, min(100, int(round(impact_percent))))
    if goal_domain == "financial":
        target_amount = coerce_number(slot_values.get("target_amount") or slot_values.get("savings_target"))
        current_saved = coerce_number(slot_values.get("current_saved_amount") or slot_values.get("current_savings"))
        monthly_capacity = coerce_number(slot_values.get("monthly_saving_capacity"))
        if monthly_capacity is None:
            income = coerce_number(slot_values.get("monthly_income"))
            fixed_expenses = coerce_number(slot_values.get("monthly_fixed_expenses"))
            debt = coerce_number(slot_values.get("existing_debt"))
            if None not in (income, fixed_expenses, debt):
                monthly_capacity = max(0.0, float(income) - float(fixed_expenses) - float(debt))
        if None not in (target_amount, current_saved, monthly_capacity):
            months = max(1, int(round(stated_timeline_days / 30.0)))
            achievable = float(current_saved) + float(monthly_capacity) * months
            capped = min(float(target_amount), achievable)
            return f"Reach about {capped:.0f} toward your savings target in this period."

    months_label = max(1, int(round(stated_timeline_days / 30.0)))
    full_months = max(1, int(round(estimated_timeline_days / 30.0)))
    return (
        f"Complete roughly {coverage}% of the full goal in ~{months_label} month(s), "
        f"then finish in ~{full_months} month(s)."
    )


def compute_timeline_realism(
    *,
    goal_domain: str,
    slot_values: dict,
    health_profile,
    stated_timeline_days: int,
    today: date | None = None,
) -> dict:
    today_value = today or timezone.localdate()
    estimated_timeline_days = estimate_timeline_days(
        goal_domain=goal_domain,
        slot_values=slot_values,
        health_profile=health_profile,
    )
    impact_percent = round(
        min(100.0, (stated_timeline_days / max(1, estimated_timeline_days)) * 100.0),
        1,
    )
    verdict = "realistic" if impact_percent >= 85.0 else "unrealistic"
    projected_full_goal_completion_date = (today_value + timedelta(days=estimated_timeline_days)).isoformat()

    return {
        "verdict": verdict,
        "achievable_sub_goal": build_achievable_sub_goal_text(
            goal_domain=goal_domain,
            slot_values=slot_values,
            stated_timeline_days=stated_timeline_days,
            estimated_timeline_days=estimated_timeline_days,
            impact_percent=impact_percent,
        ),
        "projected_full_goal_completion_date": projected_full_goal_completion_date,
        "impact_percent": impact_percent,
        "stated_timeline_days": stated_timeline_days,
        "estimated_timeline_days": estimated_timeline_days,
    }


def calculate_total_weeks(*, start_date: date, end_date: date) -> int:
    return max(1, int(ceil(max(1, (end_date - start_date).days) / 7.0)))


def evaluate_finance_timeline_math(
    *,
    savings_target: float,
    current_savings: float,
    monthly_income: float,
    monthly_fixed_expenses: float,
    debt_obligations: float,
    start_date: date,
    end_date: date,
) -> dict:
    months_to_target = max(1, int(ceil(max(1, (end_date - start_date).days) / 30.0)))
    required_monthly_saving = max(0.0, (savings_target - current_savings) / months_to_target)
    available_surplus = monthly_income - monthly_fixed_expenses - debt_obligations
    feasible = required_monthly_saving <= available_surplus

    months_needed = None
    if not feasible:
        months_needed = max(
            1,
            int(ceil((savings_target - current_savings) / max(1.0, available_surplus))),
        )

    return {
        "feasible": feasible,
        "months_to_target": months_to_target,
        "required_monthly_saving": required_monthly_saving,
        "available_surplus": available_surplus,
        "months_needed": months_needed,
    }
