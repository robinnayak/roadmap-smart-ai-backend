from django.utils import timezone
from django.db.models import Sum
import re

from goal.models import Goal, SubGoal, Task, UserFinancialProfile
from goal.serializers import GoalListSerializer, GoalSerializer
from goal.services.create_contract import (
    normalize_goal_create_payload,
)
from goal.services.category_resolver import (
    classify_goal_category,
    DEFAULT_GOAL_CATEGORY,
)
from goal.services.category_pillars import canonical_to_pillar, resolve_canonical_category
from goal.services.financial_intelligence import calculate_feasibility


GIE_GOAL_DOMAIN_TO_CATEGORY = {
    "running_endurance": "fitness",
    "nutrition": "nutrition",
    "wellness": "wellness",
    "finance": "finance",
    "financial": "finance",
    "skill_acquisition": "learning",
    "learning": "learning",
    "career": "career",
    "business": "business",
}


def sanitize_goal_payload(request_data):
    data = normalize_goal_create_payload(request_data.copy())
    if "start_date" not in data:
        data["start_date"] = timezone.localdate()
    data.pop("categories", None)
    data.pop("tags", None)
    return data


def _build_infeasible_payload(*, feasibility, needs_profile_review: bool):
    return {
        "financial_feasibility": {
            "status": "infeasible",
            "message": feasibility.message,
            "suggested_target_date": (
                feasibility.suggested_target_date.isoformat()
                if feasibility.suggested_target_date
                else None
            ),
            "achievable_amount_by_original_date": str(
                feasibility.achievable_amount_by_original_date
            ),
        },
        "needs_profile_review": needs_profile_review,
    }


def evaluate_financial_goal_feasibility(*, user, validated_data, instance=None):
    primary_category = validated_data.get("primary_category") or (
        instance.primary_category if instance else None
    )
    if primary_category != "finance":
        return {}, None

    profile = UserFinancialProfile.objects.filter(user=user).first()
    if not profile:
        return {}, {
            "error": "validation_error",
            "details": {
                "financial_profile": [
                    "Complete your financial profile before creating a finance goal."
                ]
            },
        }

    target_amount = validated_data.get(
        "financial_target_amount",
        getattr(instance, "financial_target_amount", None),
    )
    current_saved = validated_data.get(
        "financial_current_saved",
        getattr(instance, "financial_current_saved", None),
    )
    target_date = validated_data.get("target_date") or (
        instance.target_date if instance else None
    )
    proceed_anyway = bool(validated_data.get("financial_proceed_anyway", False))

    if (
        target_amount is None
        or current_saved is None
        or target_date is None
    ):
        return {}, None

    feasibility = calculate_feasibility(
        target_amount=target_amount,
        current_saved=current_saved,
        target_date=target_date,
        surplus_range=profile.monthly_surplus_range,
        today=timezone.localdate(),
    )
    metadata = {
        "financial_feasibility_status": feasibility.feasibility_status,
        "financial_gap_amount": feasibility.gap_amount,
        "financial_months_remaining": feasibility.months_remaining,
        "financial_required_monthly_savings": feasibility.required_monthly_savings,
    }

    if feasibility.feasibility_status == "infeasible" and not proceed_anyway:
        return {}, _build_infeasible_payload(
            feasibility=feasibility,
            needs_profile_review=bool(profile.needs_review),
        )

    return metadata, None


def create_goal_for_user(*, request_data, user, request):
    data = sanitize_goal_payload(request_data)
    resolved_category = _resolve_trusted_goal_category(data=data)
    if resolved_category:
        data["primary_category"] = resolved_category
    else:
        data["primary_category"] = classify_goal_category(
            goal_title=str(data.get("title") or ""),
            goal_description=str(data.get("description") or ""),
            current_category=data.get("primary_category") or DEFAULT_GOAL_CATEGORY,
        )
    enforce_hierarchy_target_window = bool(
        request is not None
        and "/goal/create-with-hierarchy/" in getattr(request, "path", "")
    )
    serializer = GoalSerializer(
        data=data,
        context={
            "request": request,
            "enforce_hierarchy_target_window": enforce_hierarchy_target_window,
        },
    )
    if not serializer.is_valid():
        return None, serializer.errors

    feasibility_metadata, feasibility_error = evaluate_financial_goal_feasibility(
        user=user,
        validated_data=serializer.validated_data,
        instance=None,
    )
    if feasibility_error:
        return None, feasibility_error

    if feasibility_metadata:
        serializer.validated_data.update(feasibility_metadata)

    goal = serializer.save(user=user)

    return goal, None


def _resolve_trusted_goal_category(*, data: dict) -> str | None:
    title = str(data.get("title") or "")
    description = str(data.get("description") or "")

    primary_category = data.get("primary_category")
    if isinstance(primary_category, str) and primary_category.strip():
        return resolve_canonical_category(
            primary_category,
            data.get("category_pillar"),
            title,
            description,
        )

    goal_domain = data.get("goal_domain")
    if isinstance(goal_domain, str) and goal_domain.strip():
        mapped_category = GIE_GOAL_DOMAIN_TO_CATEGORY.get(goal_domain.strip().lower())
        if mapped_category:
            return mapped_category

    if data.get("category_pillar"):
        return resolve_canonical_category(
            None,
            data.get("category_pillar"),
            title,
            description,
        )

    return None


def get_user_goals_payload(*, user, detailed: bool):
    goals = Goal.objects.filter(user=user).prefetch_related("milestones", "attributes")
    serializer_class = GoalSerializer if detailed else GoalListSerializer
    serializer = serializer_class(goals, many=True)
    return {"count": goals.count(), "goals": serializer.data}


def build_goal_seed_data(goal):
    impact_dimensions = goal.impact_dimensions or {}
    mapped_context = _build_task_generation_context(goal=goal, impact_dimensions=impact_dimensions)
    return {
        "id": str(goal.id),
        "title": goal.title,
        "description": goal.description,
        "priority": goal.priority,
        "why_it_matters": goal.why_it_matters,
        "why_do_i_want_this": impact_dimensions.get("why_do_i_want_this", ""),
        "specific_measurable_target": impact_dimensions.get("specific_measurable_target", ""),
        "primary_category": goal.primary_category,
        "category_pillar": canonical_to_pillar(goal.primary_category),
        "resolved_category": goal.primary_category,
        "impact_dimensions": goal.impact_dimensions,
        "start_date": goal.start_date,
        "target_date": goal.target_date,
        **mapped_context,
    }


def _build_task_generation_context(*, goal, impact_dimensions: dict) -> dict:
    current_situation = _get_current_situation_context(goal)
    health_profile_context = _get_health_profile_context(goal)

    available_daily_minutes = (
        _coerce_minutes(impact_dimensions.get("available_daily_minutes"))
        or _coerce_minutes(impact_dimensions.get("daily_session_minutes"))
        or _coerce_minutes(impact_dimensions.get("daily_practice_minutes"))
        or _coerce_minutes(impact_dimensions.get("prep_time_per_day_minutes"))
        or _coerce_minutes(health_profile_context.get("daily_time_available"))
        or _coerce_minutes(current_situation.get("time_availability"))
        or 60
    )

    user_strengths = _coerce_text_list(impact_dimensions.get("user_strengths")) or _coerce_text_list(
        current_situation.get("key_skills")
    )
    user_blockers = _coerce_text_list(impact_dimensions.get("user_blockers")) or _coerce_text_list(
        current_situation.get("constraints")
    )
    motivation_style = (
        _coerce_text(impact_dimensions.get("motivation_style"))
        or _coerce_text(health_profile_context.get("motivation_style"))
        or _derive_motivation_style(
            _coerce_text(impact_dimensions.get("motivation_driver"))
            or _coerce_text(impact_dimensions.get("why_do_i_want_this"))
            or _coerce_text(impact_dimensions.get("specific_measurable_target"))
        )
        or "intrinsic"
    )

    return {
        "available_daily_minutes": available_daily_minutes,
        "user_strengths": user_strengths,
        "user_blockers": user_blockers,
        "motivation_style": motivation_style,
    }


def _get_current_situation_context(goal) -> dict:
    try:
        personal_details = getattr(goal.user, "user_personal_details", None)
        current_situation = (
            getattr(personal_details, "current_situation_goal", None)
            if personal_details is not None
            else None
        )
    except Exception:
        current_situation = None

    if not current_situation:
        return {}

    return {
        "key_skills": current_situation.key_skills,
        "constraints": current_situation.constraints,
        "time_availability": current_situation.time_availability,
    }


def _get_health_profile_context(goal) -> dict:
    try:
        from routine.models import HealthProfile
    except Exception:
        return {}

    profile = (
        HealthProfile.objects.filter(user=goal.user, is_active=True)
        .order_by("-updated_at", "-created_at")
        .first()
    )
    if not profile:
        return {}

    return {
        "motivation_style": profile.motivation_style,
        "daily_time_available": profile.daily_time_available,
    }


def _coerce_text(value) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _coerce_text_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _coerce_minutes(value) -> int | None:
    if isinstance(value, (int, float)):
        return max(0, int(round(float(value))))
    if not isinstance(value, str):
        return None

    normalized = value.strip().lower()
    if not normalized:
        return None

    direct_match = re.search(r"(\d+)", normalized)
    if not direct_match:
        return None

    amount = int(direct_match.group(1))
    if "hour" in normalized:
        return amount * 60
    return amount


def _derive_motivation_style(value: str) -> str:
    normalized = (value or "").strip().lower()
    if not normalized:
        return ""
    if any(token in normalized for token in ("deadline", "date", "amount", "save", "target", "race", "event")):
        return "outcome-driven"
    if any(token in normalized for token in ("coach", "mentor", "manager", "accountability")):
        return "accountability-driven"
    return "intrinsic"


def get_goal_with_hierarchy_for_user(*, goal_id, user):
    try:
        return (
            Goal.objects.prefetch_related("milestones__subgoals__tasks")
            .select_related("attributes")
            .get(id=goal_id, user=user)
        )
    except Goal.DoesNotExist:
        return None


def build_goal_hierarchy_payload(*, goal, today):
    goal_data = {
        "id": str(goal.id),
        "title": goal.title,
        "description": goal.description,
        "why_it_matters": goal.why_it_matters,
        "primary_category": goal.primary_category,
        "category_pillar": canonical_to_pillar(goal.primary_category),
        "priority": goal.priority,
        "status": goal.status,
        "progress_percentage": goal.progress_percentage,
        "start_date": goal.start_date.isoformat() if goal.start_date else None,
        "target_date": goal.target_date.isoformat() if goal.target_date else None,
        "days_remaining": goal.days_remaining,
        "is_overdue": goal.is_overdue,
        "is_ai_generated": goal.is_ai_generated,
        "ai_feasibility_score": goal.ai_feasibility_score,
    }

    on_track = None
    if goal.start_date and goal.target_date:
        total_days = (goal.target_date - goal.start_date).days
        elapsed_days = (today - goal.start_date).days
        if total_days > 0:
            expected = round((elapsed_days / total_days) * 100, 1)
            actual = goal.progress_percentage
            on_track = {
                "is_on_track": actual >= expected - 10,
                "expected_progress": expected,
                "actual_progress": actual,
                "difference": round(actual - expected, 1),
            }

    milestones_data = []
    for milestone in goal.milestones.all().order_by("display_order"):
        subgoals_data = []
        milestone_progress_values = []

        for subgoal in milestone.subgoals.all().order_by("display_order"):
            tasks_data = []
            for task in subgoal.tasks.all().order_by("display_order"):
                tasks_data.append(
                    {
                        "id": str(task.id),
                        "title": task.title,
                        "description": task.description,
                        "task_type": task.task_type,
                        "item_type": task.item_type,
                        "frequency": task.frequency,
                        "difficulty_level": task.difficulty_level,
                        "session_type": task.session_type,
                        "trigger_after_days": task.trigger_after_days,
                        "is_prerequisite": task.is_prerequisite,
                        "sequence_position": task.sequence_position,
                        "rationale": task.rationale,
                        "priority": task.priority,
                        "status": task.status,
                        "display_order": task.display_order,
                        "estimated_duration_minutes": task.estimated_duration_minutes,
                        "actual_duration_minutes": task.actual_duration_minutes,
                        "scheduled_date": task.scheduled_date.isoformat()
                        if task.scheduled_date
                        else None,
                        "completed_at": task.completed_at.isoformat()
                        if task.completed_at
                        else None,
                        "is_ai_generated": task.is_ai_generated,
                    }
                )

            total_tasks = len(tasks_data)
            completed_tasks = sum(1 for t in tasks_data if t["status"] == "completed")
            subgoal_progress = (
                round((completed_tasks / total_tasks) * 100)
                if total_tasks
                else (subgoal.progress_percentage or 0)
            )
            milestone_progress_values.append(subgoal_progress)

            subgoals_data.append(
                {
                    "id": str(subgoal.id),
                    "title": subgoal.title,
                    "description": subgoal.description,
                    "priority": subgoal.priority,
                    "status": subgoal.status,
                    "progress_percentage": subgoal_progress,
                    "week_number": subgoal.week_number,
                    "display_order": subgoal.display_order,
                    "start_date": subgoal.start_date.isoformat()
                    if subgoal.start_date
                    else None,
                    "target_date": subgoal.target_date.isoformat()
                    if subgoal.target_date
                    else None,
                    "completed_date": subgoal.completed_date.isoformat()
                    if subgoal.completed_date
                    else None,
                    "is_ai_generated": subgoal.is_ai_generated,
                    "tasks": tasks_data,
                    "task_counts": {
                        "total": total_tasks,
                        "completed": completed_tasks,
                        "pending": total_tasks - completed_tasks,
                    },
                }
            )

        milestone_progress = (
            round(sum(milestone_progress_values) / len(milestone_progress_values))
            if milestone_progress_values
            else (milestone.progress_percentage or 0)
        )
        milestones_data.append(
            {
                "id": str(milestone.id),
                "title": milestone.title,
                "description": milestone.description,
                "success_criteria": milestone.success_criteria,
                "priority": milestone.priority,
                "status": milestone.status,
                "progress_percentage": milestone_progress,
                "display_order": milestone.display_order,
                "start_date": milestone.start_date.isoformat()
                if milestone.start_date
                else None,
                "target_date": milestone.target_date.isoformat()
                if milestone.target_date
                else None,
                "completed_date": milestone.completed_date.isoformat()
                if milestone.completed_date
                else None,
                "is_ai_generated": milestone.is_ai_generated,
                "subgoals": subgoals_data,
                "subgoal_count": len(subgoals_data),
            }
        )

    all_milestones = goal.milestones.all()
    total_m = all_milestones.count()
    completed_m = all_milestones.filter(status="completed").count()

    all_subgoals = SubGoal.objects.filter(milestone__goal=goal)
    total_sg = all_subgoals.count()
    completed_sg = all_subgoals.filter(status="completed").count()

    all_tasks = Task.objects.filter(subgoal__milestone__goal=goal)
    total_t = all_tasks.count()
    completed_t = all_tasks.filter(status="completed").count()
    est_minutes = all_tasks.aggregate(s=Sum("estimated_duration_minutes"))["s"] or 0
    actual_minutes = all_tasks.filter(actual_duration_minutes__isnull=False).aggregate(
        s=Sum("actual_duration_minutes")
    )["s"] or 0

    stats = {
        "milestones": {
            "total": total_m,
            "completed": completed_m,
            "completion_rate": round(completed_m / total_m * 100, 1) if total_m else 0,
        },
        "subgoals": {
            "total": total_sg,
            "completed": completed_sg,
            "completion_rate": round(completed_sg / total_sg * 100, 1) if total_sg else 0,
        },
        "tasks": {
            "total": total_t,
            "completed": completed_t,
            "completion_rate": round(completed_t / total_t * 100, 1) if total_t else 0,
        },
        "time": {
            "estimated_hours": round(est_minutes / 60, 1),
            "actual_hours": round(actual_minutes / 60, 1),
        },
    }

    return {
        "goal": goal_data,
        "on_track": on_track,
        "milestones": milestones_data,
        "stats": stats,
    }
