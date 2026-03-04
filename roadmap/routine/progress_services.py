from datetime import datetime, timedelta

from django.db.models import Count, Q, Sum
from django.utils import timezone

from goal.models import Goal, Milestone, Task
from routine.models import DailyTaskItem, DailyTaskList, DisciplineStreak, HabitTracker
from routine.serializers import DailyTaskListSummarySerializer, DisciplineStreakSerializer
from routine.services import get_or_create_today_task_list


HABIT_STYLE_MAP = {
    "morning": {
        "iconKey": "coffee",
        "color": "from-orange-500 to-amber-500",
        "bgColor": "bg-orange-100 dark:bg-orange-900/20",
    },
    "coding": {
        "iconKey": "target",
        "color": "from-blue-500 to-cyan-500",
        "bgColor": "bg-blue-100 dark:bg-blue-900/20",
    },
    "workout": {
        "iconKey": "dumbbell",
        "color": "from-red-500 to-pink-500",
        "bgColor": "bg-red-100 dark:bg-red-900/20",
    },
    "meditation": {
        "iconKey": "moon",
        "color": "from-purple-500 to-violet-500",
        "bgColor": "bg-purple-100 dark:bg-purple-900/20",
    },
    "reading": {
        "iconKey": "book-open",
        "color": "from-green-500 to-emerald-500",
        "bgColor": "bg-green-100 dark:bg-green-900/20",
    },
    "financial": {
        "iconKey": "dollar-sign",
        "color": "from-teal-500 to-cyan-500",
        "bgColor": "bg-teal-100 dark:bg-teal-900/20",
    },
}

CATEGORY_STYLE_MAP = {
    "financial": {
        "iconKey": "dollar-sign",
        "color": "from-green-500 to-emerald-500",
    },
    "career": {
        "iconKey": "briefcase",
        "color": "from-blue-500 to-cyan-500",
    },
    "health": {
        "iconKey": "heart",
        "color": "from-red-500 to-pink-500",
    },
    "personal": {
        "iconKey": "users",
        "color": "from-purple-500 to-violet-500",
    },
}

ALLOWED_PERIODS = {"week", "month", "year", "all"}


def _relative_date_label(value_date, today):
    delta_days = (today - value_date).days
    if delta_days <= 0:
        return "Today"
    if delta_days == 1:
        return "1 day ago"
    if delta_days < 7:
        return f"{delta_days} days ago"
    if delta_days < 30:
        weeks = delta_days // 7
        return f"{weeks} week ago" if weeks == 1 else f"{weeks} weeks ago"
    months = max(1, delta_days // 30)
    return f"{months} month ago" if months == 1 else f"{months} months ago"


def _detect_habit_style(habit_name: str):
    name = (habit_name or "").lower()
    if any(k in name for k in ("journal", "morning", "wake", "early")):
        return HABIT_STYLE_MAP["morning"]
    if any(k in name for k in ("code", "learn", "study", "project")):
        return HABIT_STYLE_MAP["coding"]
    if any(k in name for k in ("workout", "run", "gym", "exercise")):
        return HABIT_STYLE_MAP["workout"]
    if any(k in name for k in ("meditation", "mindful", "breathe")):
        return HABIT_STYLE_MAP["meditation"]
    if any(k in name for k in ("read", "book")):
        return HABIT_STYLE_MAP["reading"]
    if any(k in name for k in ("finance", "money", "trade", "budget", "invest")):
        return HABIT_STYLE_MAP["financial"]
    return HABIT_STYLE_MAP["coding"]


def resolve_target_date(selected_date_str: str | None, today):
    if not selected_date_str:
        return today
    try:
        target_date = datetime.strptime(selected_date_str, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("Invalid date format. Use YYYY-MM-DD.") from exc
    if target_date > today:
        raise ValueError("Date cannot be in the future.")
    return target_date


def resolve_period_window(period: str, target_date):
    normalized_period = period if period in ALLOWED_PERIODS else "week"
    window_days = {
        "week": 7,
        "month": 30,
        "year": 365,
        "all": None,
    }[normalized_period]
    start_date = target_date - timedelta(days=window_days - 1) if window_days else None
    return normalized_period, start_date


def build_week_overview_payload(user, today=None):
    today = today or timezone.localdate()
    start_of_week = today - timedelta(days=today.weekday())

    task_lists = DailyTaskList.objects.filter(
        user=user,
        date__range=(start_of_week, start_of_week + timedelta(days=6)),
    )
    task_list_by_date = {tl.date: tl for tl in task_lists}

    week_data = []
    for day_offset in range(7):
        day = start_of_week + timedelta(days=day_offset)
        tl = task_list_by_date.get(day)
        week_data.append(
            {
                "date": day.isoformat(),
                "day_name": day.strftime("%A"),
                "is_today": day == today,
                "data": DailyTaskListSummarySerializer(tl).data if tl else None,
            }
        )

    return {"week_start": start_of_week.isoformat(), "days": week_data}


def build_streak_payload(user):
    streak, _ = DisciplineStreak.objects.get_or_create(user=user)
    return {"streak": DisciplineStreakSerializer(streak).data}


def build_progress_overview_payload(
    *,
    user,
    period: str,
    selected_date_str: str | None,
    today=None,
):
    today = today or timezone.localdate()
    target_date = resolve_target_date(selected_date_str, today)
    normalized_period, start_date = resolve_period_window(period, target_date)

    goals_qs = Goal.objects.filter(user=user).exclude(status="cancelled").values(
        "id", "primary_category"
    )
    goals = list(goals_qs)

    task_progress_rows = (
        Task.objects.filter(subgoal__milestone__goal__user=user)
        .values("subgoal__milestone__goal_id")
        .annotate(
            total_tasks=Count("id"),
            completed_tasks=Count(
                "id",
                filter=Q(completed_at__isnull=False, completed_at__date__lte=target_date),
            ),
        )
    )
    task_progress_map = {
        str(row["subgoal__milestone__goal_id"]): row for row in task_progress_rows
    }

    milestone_rows = (
        Milestone.objects.filter(goal__user=user)
        .values("goal_id")
        .annotate(
            total_milestones=Count("id"),
            completed_milestones=Count(
                "id",
                filter=Q(
                    status="completed",
                    completed_date__isnull=False,
                    completed_date__lte=target_date,
                ),
            ),
        )
    )
    milestone_map = {str(row["goal_id"]): row for row in milestone_rows}

    goal_snapshots = []
    for goal in goals:
        goal_id = str(goal["id"])
        task_metrics = task_progress_map.get(goal_id)
        milestone_metrics = milestone_map.get(goal_id)

        progress_as_of = 0
        if task_metrics and (task_metrics.get("total_tasks") or 0) > 0:
            progress_as_of = round(
                (task_metrics.get("completed_tasks", 0) / task_metrics.get("total_tasks", 1))
                * 100
            )
        elif milestone_metrics and (milestone_metrics.get("total_milestones") or 0) > 0:
            progress_as_of = round(
                (
                    milestone_metrics.get("completed_milestones", 0)
                    / milestone_metrics.get("total_milestones", 1)
                )
                * 100
            )

        if progress_as_of == 100:
            status_as_of = "completed"
        elif progress_as_of > 0:
            status_as_of = "in_progress"
        else:
            status_as_of = "not_started"

        goal_snapshots.append(
            {
                "id": goal_id,
                "primary_category": goal["primary_category"],
                "progress_percentage": progress_as_of,
                "status": status_as_of,
            }
        )

    total_goals = len(goals)
    overall_progress = (
        round(sum(g["progress_percentage"] or 0 for g in goal_snapshots) / total_goals)
        if total_goals
        else 0
    )
    total_goals_completed = sum(1 for g in goal_snapshots if g["status"] == "completed")
    active_goals = sum(1 for g in goal_snapshots if g["status"] not in {"completed", "cancelled"})

    task_lists_qs = DailyTaskList.objects.filter(user=user)
    if start_date:
        task_lists_qs = task_lists_qs.filter(date__gte=start_date, date__lte=target_date)
    else:
        task_lists_qs = task_lists_qs.filter(date__lte=target_date)

    task_totals = task_lists_qs.aggregate(
        total=Sum("total_tasks"),
        completed=Sum("completed_tasks"),
    )
    success_rate = (
        round((task_totals["completed"] or 0) / max(task_totals["total"] or 0, 1) * 100)
        if (task_totals["total"] or 0) > 0
        else 0
    )

    streak, _ = DisciplineStreak.objects.get_or_create(user=user)
    days_active = streak.total_days_tracked or DailyTaskList.objects.filter(
        user=user, completed_tasks__gt=0
    ).values("date").distinct().count()

    overall_stats = {
        "overallProgress": overall_progress,
        "totalGoalsCompleted": total_goals_completed,
        "activeGoals": active_goals,
        "successRate": success_rate,
        "currentStreak": streak.current_streak_days,
        "maxStreak": streak.longest_streak_days,
        "daysActive": days_active,
    }

    habit_items_qs = DailyTaskItem.objects.filter(
        task_list__user=user,
        item_type="habit",
        habit__isnull=False,
    ).select_related("habit", "task_list")
    if start_date:
        habit_items_qs = habit_items_qs.filter(
            task_list__date__gte=start_date, task_list__date__lte=target_date
        )
    else:
        habit_items_qs = habit_items_qs.filter(task_list__date__lte=target_date)

    habit_aggregate = {}
    for item in habit_items_qs:
        if not item.habit_id:
            continue
        bucket = habit_aggregate.setdefault(
            str(item.habit_id),
            {"total": 0, "completed": 0, "by_date": []},
        )
        bucket["total"] += 1
        if item.is_completed:
            bucket["completed"] += 1
        bucket["by_date"].append((item.task_list.date, 1 if item.is_completed else 0))

    habits = HabitTracker.objects.filter(user=user, is_active=True).order_by("name")
    habit_stats = []
    for habit in habits:
        metrics = habit_aggregate.get(str(habit.id), {"total": 0, "completed": 0, "by_date": []})
        total_occurrences = metrics["total"]
        completed_occurrences = metrics["completed"]
        completion_rate = (
            round((completed_occurrences / total_occurrences) * 100)
            if total_occurrences
            else 0
        )

        trend = "steady"
        samples = sorted(metrics["by_date"], key=lambda pair: pair[0])
        if len(samples) >= 4:
            mid = len(samples) // 2
            first = samples[:mid]
            second = samples[mid:]
            first_rate = sum(v for _, v in first) / max(len(first), 1)
            second_rate = sum(v for _, v in second) / max(len(second), 1)
            if second_rate - first_rate > 0.05:
                trend = "up"
            elif first_rate - second_rate > 0.05:
                trend = "down"

        longest_base = habit.longest_streak or 1
        streak_factor = min(100, round((habit.current_streak / longest_base) * 100))
        consistency_score = round((completion_rate * 0.8) + (streak_factor * 0.2))
        style = _detect_habit_style(habit.name)
        habit_key = habit.name.strip().lower().replace(" ", "_")

        habit_stats.append(
            {
                "key": habit_key,
                "name": habit.name,
                "iconKey": style["iconKey"],
                "completionRate": completion_rate,
                "currentStreak": habit.current_streak,
                "longestStreak": habit.longest_streak,
                "color": style["color"],
                "bgColor": style["bgColor"],
                "consistencyScore": consistency_score,
                "trend": trend,
            }
        )

    category_stats = []
    for category in ("financial", "career", "health", "personal"):
        category_goals = [g for g in goal_snapshots if g["primary_category"] == category]
        total = len(category_goals)
        completed = sum(1 for g in category_goals if g["status"] == "completed")
        in_progress = sum(1 for g in category_goals if g["status"] == "in_progress")
        avg_progress = (
            round(sum(g["progress_percentage"] or 0 for g in category_goals) / total)
            if total
            else 0
        )
        trend = "up" if avg_progress >= 70 else "steady" if avg_progress >= 40 else "down"
        style = CATEGORY_STYLE_MAP[category]
        category_stats.append(
            {
                "name": category.capitalize(),
                "iconKey": style["iconKey"],
                "totalGoals": total,
                "completedGoals": completed,
                "inProgressGoals": in_progress,
                "completionRate": avg_progress,
                "color": style["color"],
                "trend": trend,
            }
        )

    weekly_start = target_date - timedelta(days=6)
    weekly_task_lists = DailyTaskList.objects.filter(
        user=user, date__range=(weekly_start, target_date)
    )
    weekly_by_date = {item.date: item for item in weekly_task_lists}
    weekly_data = []
    for offset in range(7):
        day = weekly_start + timedelta(days=offset)
        row = weekly_by_date.get(day)
        completion = row.completion_percentage if row else 0
        weekly_data.append(
            {
                "date": day.strftime("%a"),
                "completion": completion,
                "tasksCompleted": row.completed_tasks if row else 0,
                "mood": max(5, round(completion / 10)) if row else 5,
            }
        )

    milestones_payload = []
    completed_milestones = Milestone.objects.filter(
        goal__user=user,
        status="completed",
        completed_date__isnull=False,
        completed_date__lte=target_date,
    ).order_by("-completed_date")[:4]

    for milestone in completed_milestones:
        milestones_payload.append(
            {
                "title": milestone.title,
                "date": _relative_date_label(milestone.completed_date, target_date),
                "icon": "🏆",
                "sortDate": milestone.completed_date,
            }
        )

    completed_goals_recent = Goal.objects.filter(user=user, status="completed").order_by("-updated_at")[:3]
    for goal in completed_goals_recent:
        goal_date = min(goal.updated_at.date(), target_date)
        milestones_payload.append(
            {
                "title": f"Completed goal: {goal.title}",
                "date": _relative_date_label(goal_date, target_date),
                "icon": "🎯",
                "sortDate": goal_date,
            }
        )

    if streak.longest_streak_days >= 7:
        milestones_payload.append(
            {
                "title": f"{streak.longest_streak_days}-Day Discipline Streak",
                "date": "Ongoing",
                "icon": "🔥",
                "sortDate": target_date,
            }
        )

    milestones_payload = sorted(
        milestones_payload, key=lambda m: m["sortDate"], reverse=True
    )[:6]
    milestones_payload = [
        {
            "title": item["title"],
            "date": item["date"],
            "icon": item["icon"],
        }
        for item in milestones_payload
    ]

    heatmap_start = target_date - timedelta(days=34)
    heatmap_task_lists = DailyTaskList.objects.filter(
        user=user, date__range=(heatmap_start, target_date)
    )
    heatmap_by_date = {row.date: row for row in heatmap_task_lists}
    activity_heatmap = []
    for offset in range(35):
        day = heatmap_start + timedelta(days=offset)
        row = heatmap_by_date.get(day)
        completed = bool(row and row.completed_tasks > 0)
        activity_heatmap.append(
            {
                "date": day.isoformat(),
                "completed": completed,
            }
        )

    if target_date == today:
        selected_task_list, _ = get_or_create_today_task_list(user, target_date)
    else:
        selected_task_list = DailyTaskList.objects.filter(
            user=user, date=target_date
        ).first()
    if selected_task_list:
        selected_items = (
            DailyTaskItem.objects.filter(task_list=selected_task_list)
            .select_related("related_goal")
            .order_by("display_order")
        )
    else:
        selected_items = []

    today_task_sheet = []
    for item in selected_items:
        if item.is_completed:
            status = "completed"
        elif item.is_skipped:
            status = "skipped"
        else:
            status = "pending"

        category = "personal"
        if item.related_goal_id and item.related_goal and item.related_goal.primary_category:
            category = item.related_goal.primary_category

        today_task_sheet.append(
            {
                "id": str(item.id),
                "task": item.title,
                "itemType": item.item_type,
                "status": status,
                "priority": item.priority,
                "category": category,
                "goalTitle": item.related_goal.title if item.related_goal_id and item.related_goal else None,
                "timeSlot": item.time_slot,
                "suggestedTime": item.suggested_time.isoformat() if item.suggested_time else None,
                "estimatedMinutes": item.estimated_minutes,
                "pointsEarned": item.points_earned,
            }
        )

    payload = {
        "timePeriod": normalized_period,
        "selectedDate": target_date.isoformat(),
        "hasDataForDate": bool(selected_task_list),
        "existingDates": [
            d.isoformat()
            for d in DailyTaskList.objects.filter(user=user)
            .order_by("-date")
            .values_list("date", flat=True)[:120]
        ],
        "overallStats": overall_stats,
        "habitStats": habit_stats,
        "categoryStats": category_stats,
        "weeklyData": weekly_data,
        "milestones": milestones_payload,
        "activityHeatmap": activity_heatmap,
        "todayTaskSheet": today_task_sheet,
        "generatedAt": timezone.now().isoformat(),
    }

    return payload
