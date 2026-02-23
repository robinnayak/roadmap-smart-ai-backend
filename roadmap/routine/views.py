#==============================================================================
# roadmap/routine/views.py
# ==============================================================================
import logging
from datetime import datetime, timedelta

from django.db.models import Sum, Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status as http_status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from goal.models import Goal, Milestone, Task
from routine.models import DailyTaskList, DailyTaskItem, HabitTracker, DisciplineStreak
from routine.serializers import (
    DailyTaskListSerializer, DailyTaskListSummarySerializer,
    DailyTaskItemSerializer, HabitTrackerSerializer, DisciplineStreakSerializer,
)
from routine.services import get_or_create_today_task_list, update_discipline_streak

logger = logging.getLogger(__name__)


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


class TodayTaskListAPIView(APIView):
    """
    GET /api/routines/today/
    Returns today's task list, generating it if it doesn't exist yet.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        today = timezone.localdate()
        task_list, created = get_or_create_today_task_list(request.user, today)
        serializer = DailyTaskListSerializer(task_list, context={"request": request})
        response_status = http_status.HTTP_201_CREATED if created else http_status.HTTP_200_OK
        return Response({"task_list": serializer.data}, status=response_status)


class GenerateDailyTaskListAPIView(APIView):
    """
    POST /api/routines/generate/
    Body: { "date": "2026-02-05" }   ← optional, defaults to today

    Explicitly generate (or re-fetch) a task list for a given date.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        date_str = request.data.get("date")
        try:
            target_date = (
                datetime.strptime(date_str, "%Y-%m-%d").date()
                if date_str
                else timezone.localdate()
            )
        except ValueError:
            return Response(
                {"error": "Invalid date format. Use YYYY-MM-DD."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        task_list, created = get_or_create_today_task_list(request.user, target_date)
        serializer = DailyTaskListSerializer(task_list, context={"request": request})
        message = "Daily task list generated." if created else f"Task list already exists for {target_date}."
        response_status = http_status.HTTP_201_CREATED if created else http_status.HTTP_200_OK
        return Response({"message": message, "task_list": serializer.data}, status=response_status)


class CompleteTaskItemAPIView(APIView):
    """
    POST /api/routines/tasks/<task_id>/complete/
    Body: { "notes": "...", "actual_minutes": 45 }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, task_id):
        task_item = get_object_or_404(
            DailyTaskItem, id=task_id, task_list__user=request.user
        )

        if task_item.is_completed:
            return Response(
                {"message": "Task already completed."},
                status=http_status.HTTP_200_OK,
            )

        task_item.mark_completed(
            notes=request.data.get("notes", ""),
            actual_minutes=request.data.get("actual_minutes"),
        )

        # FIX: Update discipline streak after every completion.
        #      update_discipline_streak is a no-op unless the day is fully done.
        update_discipline_streak(request.user, task_item.task_list)

        task_list = task_item.task_list
        return Response(
            {
                "message": "Task completed!",
                "task": DailyTaskItemSerializer(task_item).data,
                "task_list_progress": {
                    "completion_percentage": task_list.completion_percentage,
                    "completed_tasks":       task_list.completed_tasks,
                    "total_tasks":           task_list.total_tasks,
                    "is_fully_completed":    task_list.is_fully_completed,
                },
            },
            status=http_status.HTTP_200_OK,
        )


class SkipTaskItemAPIView(APIView):
    """
    POST /api/routines/tasks/<task_id>/skip/
    Body: { "reason": "No time today" }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, task_id):
        task_item = get_object_or_404(
            DailyTaskItem, id=task_id, task_list__user=request.user
        )

        # Can't skip a completed task
        if task_item.is_completed:
            return Response(
                {"message": "Task is already completed and cannot be skipped."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        # Can't skip an already-skipped task
        if task_item.is_skipped:
            return Response(
                {"message": "Task is already skipped."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        task_item.mark_skipped(reason=request.data.get("reason", ""))
        return Response(
            {
                "message": "Task skipped.",
                "task": DailyTaskItemSerializer(task_item).data,
            },
            status=http_status.HTTP_200_OK,
        )


class WeekOverviewAPIView(APIView):
    """
    GET /api/routines/week/
    Returns summary data for each day of the current week.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        today = timezone.localdate()
        start_of_week = today - timedelta(days=today.weekday())  # Monday

        # Single query for the whole week instead of 7 separate filter() calls
        task_lists = DailyTaskList.objects.filter(
            user=request.user,
            date__range=(start_of_week, start_of_week + timedelta(days=6)),
        )
        task_list_by_date = {tl.date: tl for tl in task_lists}

        week_data = []
        for day_offset in range(7):
            day = start_of_week + timedelta(days=day_offset)
            tl  = task_list_by_date.get(day)
            week_data.append({
                "date":     day.isoformat(),
                "day_name": day.strftime("%A"),
                "is_today": day == today,
                "data":     DailyTaskListSummarySerializer(tl).data if tl else None,
            })

        return Response(
            {"week_start": start_of_week.isoformat(), "days": week_data},
            status=http_status.HTTP_200_OK,
        )


class ProgressOverviewAPIView(APIView):
    """
    GET /api/routines/progress/?period=week|month|year|all
    Returns a complete progress report payload for the frontend progress page.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        period = request.query_params.get("period", "week").lower()
        selected_date_str = request.query_params.get("date")
        today = timezone.localdate()
        if selected_date_str:
            try:
                target_date = datetime.strptime(selected_date_str, "%Y-%m-%d").date()
            except ValueError:
                return Response(
                    {"error": "Invalid date format. Use YYYY-MM-DD."},
                    status=http_status.HTTP_400_BAD_REQUEST,
                )
            if target_date > today:
                return Response(
                    {"error": "Date cannot be in the future."},
                    status=http_status.HTTP_400_BAD_REQUEST,
                )
        else:
            target_date = today

        window_days = {
            "week": 7,
            "month": 30,
            "year": 365,
            "all": None,
        }.get(period, 7)
        start_date = target_date - timedelta(days=window_days - 1) if window_days else None

        # --- Goals overview ---------------------------------------------------
        goals_qs = Goal.objects.filter(user=request.user).exclude(status="cancelled").values(
            "id", "primary_category"
        )
        goals = list(goals_qs)

        task_progress_rows = (
            Task.objects.filter(subgoal__milestone__goal__user=request.user)
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
            Milestone.objects.filter(goal__user=request.user)
            .values("goal_id")
            .annotate(
                total_milestones=Count("id"),
                completed_milestones=Count(
                    "id",
                    filter=Q(status="completed", completed_date__isnull=False, completed_date__lte=target_date),
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
                    (task_metrics.get("completed_tasks", 0) / task_metrics.get("total_tasks", 1)) * 100
                )
            elif milestone_metrics and (milestone_metrics.get("total_milestones") or 0) > 0:
                progress_as_of = round(
                    (milestone_metrics.get("completed_milestones", 0) / milestone_metrics.get("total_milestones", 1)) * 100
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
        active_goals = sum(
            1 for g in goal_snapshots if g["status"] not in {"completed", "cancelled"}
        )

        # --- Task success rate -----------------------------------------------
        task_lists_qs = DailyTaskList.objects.filter(user=request.user)
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

        streak, _ = DisciplineStreak.objects.get_or_create(user=request.user)
        days_active = streak.total_days_tracked or DailyTaskList.objects.filter(
            user=request.user, completed_tasks__gt=0
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

        # --- Habit consistency ------------------------------------------------
        habit_items_qs = DailyTaskItem.objects.filter(
            task_list__user=request.user,
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

        habits = HabitTracker.objects.filter(user=request.user, is_active=True).order_by("name")
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

            # Compare first half vs second half to infer trend.
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

        # --- Category progress ------------------------------------------------
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

        # --- Weekly chart -----------------------------------------------------
        weekly_start = target_date - timedelta(days=6)
        weekly_task_lists = DailyTaskList.objects.filter(
            user=request.user, date__range=(weekly_start, target_date)
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

        # --- Milestones -------------------------------------------------------
        milestones_payload = []
        completed_milestones = Milestone.objects.filter(
            goal__user=request.user,
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

        completed_goals_recent = Goal.objects.filter(
            user=request.user, status="completed"
        ).order_by("-updated_at")[:3]
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

        # --- 35-day activity heatmap -----------------------------------------
        heatmap_start = target_date - timedelta(days=34)
        heatmap_task_lists = DailyTaskList.objects.filter(
            user=request.user, date__range=(heatmap_start, target_date)
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

        # --- Today task tracking sheet ---------------------------------------
        if target_date == today:
            selected_task_list, _ = get_or_create_today_task_list(request.user, target_date)
        else:
            selected_task_list = DailyTaskList.objects.filter(
                user=request.user, date=target_date
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

        return Response(
            {
                "timePeriod": period if period in {"week", "month", "year", "all"} else "week",
                "selectedDate": target_date.isoformat(),
                "hasDataForDate": bool(selected_task_list),
                "existingDates": [
                    d.isoformat()
                    for d in DailyTaskList.objects.filter(user=request.user)
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
            },
            status=http_status.HTTP_200_OK,
        )


class DisciplineStreakAPIView(APIView):
    """GET /api/routines/streak/"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        streak, _ = DisciplineStreak.objects.get_or_create(user=request.user)
        return Response(
            {"streak": DisciplineStreakSerializer(streak).data},
            status=http_status.HTTP_200_OK,
        )


class HabitTrackerAPIView(APIView):
    """
    GET  /api/routines/habits/
    POST /api/routines/habits/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        habits = HabitTracker.objects.filter(user=request.user).select_related("linked_goal")
        return Response(
            {"habits": HabitTrackerSerializer(habits, many=True).data},
            status=http_status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = HabitTrackerSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(user=request.user)
            return Response(serializer.data, status=http_status.HTTP_201_CREATED)
        return Response(serializer.errors, status=http_status.HTTP_400_BAD_REQUEST)


class HabitDetailAPIView(APIView):
    """
    GET    /api/routines/habits/<habit_id>/
    PUT    /api/routines/habits/<habit_id>/
    DELETE /api/routines/habits/<habit_id>/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, habit_id):
        habit = get_object_or_404(HabitTracker, id=habit_id, user=request.user)
        return Response(
            {"habit": HabitTrackerSerializer(habit).data},
            status=http_status.HTTP_200_OK,
        )

    def put(self, request, habit_id):
        habit = get_object_or_404(HabitTracker, id=habit_id, user=request.user)
        serializer = HabitTrackerSerializer(habit, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=http_status.HTTP_200_OK)
        return Response(serializer.errors, status=http_status.HTTP_400_BAD_REQUEST)

    def delete(self, request, habit_id):
        habit = get_object_or_404(HabitTracker, id=habit_id, user=request.user)
        habit.delete()
        return Response(status=http_status.HTTP_204_NO_CONTENT)
