from django.utils import timezone
from django.db.models import Sum

from goal.models import Goal, SubGoal, Task
from goal.serializers import GoalListSerializer, GoalSerializer


def sanitize_goal_payload(request_data):
    data = request_data.copy()
    if "start_date" not in data:
        data["start_date"] = timezone.localdate()
    data.pop("categories", None)
    data.pop("tags", None)
    return data


def create_goal_for_user(*, request_data, user, request):
    data = sanitize_goal_payload(request_data)
    serializer = GoalSerializer(data=data, context={"request": request})
    if not serializer.is_valid():
        return None, serializer.errors
    goal = serializer.save(user=user)
    return goal, None


def get_user_goals_payload(*, user, detailed: bool):
    goals = Goal.objects.filter(user=user).prefetch_related("milestones", "attributes")
    serializer_class = GoalSerializer if detailed else GoalListSerializer
    serializer = serializer_class(goals, many=True)
    return {"count": goals.count(), "goals": serializer.data}


def build_goal_seed_data(goal):
    return {
        "id": str(goal.id),
        "title": goal.title,
        "description": goal.description,
        "why_it_matters": goal.why_it_matters,
        "primary_category": goal.primary_category,
        "impact_dimensions": goal.impact_dimensions,
        "start_date": goal.start_date,
        "target_date": goal.target_date,
    }


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
