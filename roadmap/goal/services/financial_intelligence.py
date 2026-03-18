from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from django.utils import timezone
from django.db.models import Q

from goal.models import Goal, GoalLink, UserFinancialProfile


SURPLUS_RANGE_TO_AMOUNT: dict[str, Decimal] = {
    "nothing_left": Decimal("0"),
    "under_10k": Decimal("10000"),
    "10k_30k": Decimal("30000"),
    "30k_70k": Decimal("70000"),
    "70k_plus": Decimal("100000"),
}


@dataclass
class FeasibilityResult:
    feasibility_status: str
    gap_amount: Decimal
    months_remaining: int
    required_monthly_savings: Decimal
    available_monthly_surplus: Decimal
    message: str
    suggested_target_date: date | None
    achievable_amount_by_original_date: Decimal


def _months_until(target_date: date, today: date) -> int:
    days = (target_date - today).days
    if days <= 0:
        return 0
    return max(1, (days + 29) // 30)


def calculate_feasibility(
    *,
    target_amount: Decimal,
    current_saved: Decimal,
    target_date: date,
    surplus_range: str,
    today: date,
) -> FeasibilityResult:
    gap = max(Decimal("0"), target_amount - current_saved)
    months_remaining = _months_until(target_date, today)
    if months_remaining <= 0:
        required = gap if gap > 0 else Decimal("0")
    else:
        required = (gap / Decimal(months_remaining)).quantize(Decimal("0.01"))

    available = SURPLUS_RANGE_TO_AMOUNT.get(surplus_range, Decimal("0"))
    stretch_limit = available * Decimal("1.8")

    if required <= available:
        status = "pass"
        message = "This goal is feasible with your current surplus."
    elif required <= stretch_limit:
        status = "stretch"
        message = "This goal requires growing your income, not just saving."
    else:
        status = "infeasible"
        message = "Based on your current profile and timeline, this goal needs adjustment."

    suggested_target_date = None
    if available > 0 and gap > 0:
        required_months = int((gap / available).to_integral_value(rounding="ROUND_UP"))
        suggested_target_date = today.replace(day=1)
        year_delta, month_index = divmod((suggested_target_date.month - 1) + required_months, 12)
        suggested_target_date = suggested_target_date.replace(
            year=suggested_target_date.year + year_delta,
            month=month_index + 1,
        )

    achievable = current_saved + (available * Decimal(max(0, months_remaining)))
    if achievable > target_amount:
        achievable = target_amount

    return FeasibilityResult(
        feasibility_status=status,
        gap_amount=gap.quantize(Decimal("0.01")),
        months_remaining=months_remaining,
        required_monthly_savings=required,
        available_monthly_surplus=available,
        message=message,
        suggested_target_date=suggested_target_date,
        achievable_amount_by_original_date=achievable.quantize(Decimal("0.01")),
    )


def mark_profile_review_needed(*, user, reason: str) -> None:
    profile = UserFinancialProfile.objects.filter(user=user).first()
    if not profile:
        return
    profile.needs_review = True
    profile.review_reason = reason[:255]
    profile.save(update_fields=["needs_review", "review_reason", "updated_at", "last_updated"])


def evaluate_profile_review_for_goal(*, goal: Goal) -> None:
    has_links = GoalLink.objects.filter(contributing_goal=goal).exists()
    if not has_links:
        return

    # Only linked contributing-goal events should trigger profile review.
    if goal.primary_category in {"career", "business"} and goal.status == "completed":
        mark_profile_review_needed(
            user=goal.user,
            reason="A linked career goal was completed and may change income.",
        )
        return

    if goal.primary_category != "finance" and goal.status in {"paused", "cancelled"}:
        mark_profile_review_needed(
            user=goal.user,
            reason="A contributing goal was paused/cancelled. Review financial profile.",
        )


def evaluate_profile_review_for_user(*, user) -> tuple[bool, str]:
    linked_goals = Goal.objects.filter(
        user=user,
        contributing_links__isnull=False,
    ).distinct()

    if linked_goals.filter(primary_category__in=["career", "business"], status="completed").exists():
        return True, "A linked career goal was completed and may change income."

    if linked_goals.filter(
        ~Q(primary_category="finance"),
        status__in=["paused", "cancelled"],
    ).exists():
        return True, "A contributing goal was paused/cancelled. Review financial profile."

    return False, ""


EMPLOYMENT_PROFILE_HINTS = {
    "student": "Use foundation tasks: skill building, credentials, and habit-first small savings.",
    "aspiring_founder": "Use dual-track startup milestones with personal runway protection.",
    "early_career": "Use acceleration tasks: salary benchmark, portfolio impact, and side-income experiments.",
    "salaried_employee": "Use raise/promotion and controlled freelance expansion tasks.",
    "freelancer": "Use pipeline smoothing, rate increase strategy, and client diversification tasks.",
    "business_owner": "Use margin analysis, weekly revenue targets, and owner draw discipline tasks.",
    "between_jobs": "Use conservative bridge-income and expense control tasks before growth bets.",
}


def build_profile_plan_hint(profile: UserFinancialProfile | None) -> str:
    if not profile:
        return EMPLOYMENT_PROFILE_HINTS["between_jobs"]
    return EMPLOYMENT_PROFILE_HINTS.get(profile.employment_type, EMPLOYMENT_PROFILE_HINTS["between_jobs"])


EMPLOYMENT_WEEKLY_ACTION_TEMPLATES: dict[str, list[str]] = {
    "student": [
        "Complete one market-ready skill micro-project and publish it weekly.",
        "Block 4 focused sessions for internship or stipend income opportunities.",
        "Track weekly savings transfer from allowance/part-time income.",
    ],
    "aspiring_founder": [
        "Run one customer-discovery loop and close one paid pilot every week.",
        "Reserve weekly runway review to cap burn and protect savings.",
        "Ship one high-leverage growth experiment tied to revenue.",
    ],
    "early_career": [
        "Deliver one visible impact artifact weekly for promotion velocity.",
        "Run one salary/market benchmark and negotiate progress checkpoints.",
        "Execute one side-income experiment with strict weekly KPI review.",
    ],
    "salaried_employee": [
        "Ship one promotion-linked work outcome each week.",
        "Run one focused upskilling block tied to raise eligibility.",
        "Build one repeatable side-income asset or retained client prospect.",
    ],
    "freelancer": [
        "Prospect and pitch weekly to keep a full future pipeline.",
        "Raise rates or package value for one client segment each cycle.",
        "Reserve weekly ops block for receivables and cashflow stabilization.",
    ],
    "business_owner": [
        "Review weekly margin by offer and cut low-return activities.",
        "Set one revenue-driving owner action with measurable weekly KPI.",
        "Reinvest by rule: protect savings target before discretionary spend.",
    ],
    "between_jobs": [
        "Secure bridge income actions weekly before growth bets.",
        "Apply to role pipeline with weekly conversion targets.",
        "Maintain strict expense controls and protected emergency savings.",
    ],
}


LINK_IMPACT_MULTIPLIERS: dict[str, Decimal] = {
    "income_growth": Decimal("0.40"),
    "skill_building": Decimal("0.22"),
    "lifestyle": Decimal("0.12"),
}


def _add_months(month_anchor: date, offset: int) -> date:
    year_delta, month_index = divmod((month_anchor.month - 1) + offset, 12)
    return month_anchor.replace(year=month_anchor.year + year_delta, month=month_index + 1, day=1)


def build_financial_plan_summary(*, goal: Goal, user) -> dict | None:
    if goal.primary_category != "finance":
        return None

    profile = UserFinancialProfile.objects.filter(user=user).first()
    profile_type = profile.employment_type if profile else "between_jobs"
    weekly_actions = EMPLOYMENT_WEEKLY_ACTION_TEMPLATES.get(
        profile_type,
        EMPLOYMENT_WEEKLY_ACTION_TEMPLATES["between_jobs"],
    )

    feasibility_status = goal.financial_feasibility_status or "pass"
    required_monthly = Decimal(goal.financial_required_monthly_savings or 0).quantize(Decimal("0.01"))
    available_monthly = SURPLUS_RANGE_TO_AMOUNT.get(
        profile.monthly_surplus_range if profile else "nothing_left",
        Decimal("0"),
    ).quantize(Decimal("0.01"))
    gap_amount = Decimal(goal.financial_gap_amount or 0).quantize(Decimal("0.01"))

    links = GoalLink.objects.filter(source_goal=goal).select_related("contributing_goal")
    linked_goal_contributions: list[dict] = []
    total_linked_impact = Decimal("0.00")
    for link in links:
        multiplier = LINK_IMPACT_MULTIPLIERS.get(link.link_type, Decimal("0.10"))
        expected_impact = (available_monthly * multiplier).quantize(Decimal("0.01"))
        total_linked_impact += expected_impact
        linked_goal_contributions.append(
            {
                "contributing_goal_id": str(link.contributing_goal_id),
                "contribution_type": link.link_type,
                "expected_monthly_impact": float(expected_impact),
            }
        )

    uplift_gap = max(Decimal("0.00"), required_monthly - (available_monthly + total_linked_impact))
    income_growth_required = feasibility_status in {"stretch", "infeasible"}

    months_remaining = max(1, int(goal.financial_months_remaining or 1))
    milestone_count = min(months_remaining, 6)
    month_anchor = timezone.localdate().replace(day=1)
    current_saved = Decimal(goal.financial_current_saved or 0)
    target_amount = Decimal(goal.financial_target_amount or 0)
    monthly_milestones: list[dict] = []
    for idx in range(milestone_count):
        month_value = _add_months(month_anchor, idx)
        cumulative_target = current_saved + (required_monthly * Decimal(idx + 1))
        if target_amount > 0:
            cumulative_target = min(cumulative_target, target_amount)
        monthly_milestones.append(
            {
                "month": month_value.isoformat(),
                "savings_target": float(required_monthly),
                "cumulative_target": float(cumulative_target.quantize(Decimal("0.01"))),
                "checkpoint_note": weekly_actions[idx % len(weekly_actions)],
            }
        )

    return {
        "feasibility_summary": {
            "feasibility_status": feasibility_status,
            "required_monthly_savings": float(required_monthly),
            "available_monthly_surplus": float(available_monthly),
            "gap_amount": float(gap_amount),
        },
        "income_growth_path": {
            "required": income_growth_required,
            "actions": weekly_actions,
            "target_monthly_uplift": float(uplift_gap),
        },
        "linked_goal_contributions": linked_goal_contributions,
        "monthly_milestones": monthly_milestones,
        "employment_profile_used": profile_type,
    }
