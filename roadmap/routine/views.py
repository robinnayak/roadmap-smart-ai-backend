#==============================================================================
# roadmap/routine/views.py
# ==============================================================================
import logging
from collections import defaultdict

from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from django.db import transaction, models
from django.utils import timezone
from rest_framework import status as http_status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from routine.models import (
    DailyTaskItem,
    HabitTracker,
    DailyTaskList,
    HealthProfile,
    GoalProgressEntry,
    DailyBrief,
)
from goal.models import Goal
from routine.serializers import (
    DailyTaskListSerializer,
    DailyTaskItemSerializer,
    HabitTrackerSerializer,
    HealthProfileSerializer,
    HabitRecommendationSerializer,
    GoalProgressEntrySerializer,
    DailyBriefSerializer,
    TrackStatusRequestSerializer,
    HabitSuggestionRequestSerializer,
    HabitSuggestionSnoozeRequestSerializer,
    GenerateDailyTaskListRequestSerializer, CompleteTaskItemRequestSerializer,
    SkipTaskItemRequestSerializer,
    ReorderRoutineTasksRequestSerializer,
    CreateRoutineTaskRequestSerializer,
    UpdateRoutineTaskRequestSerializer,
)
from routine.daily_brief_service import get_or_generate_today_brief
from routine.health_profile_selector import activate_profile
from routine.habit_recommendation_service import generate_habit_recommendations_for_user
from routine.services import (
    get_or_create_today_task_list,
    update_discipline_streak,
    validate_manual_task_schedule_fit,
)
from routine.system_habits_service import seed_system_habits_for_user
from routine.progress_services import (
    build_progress_overview_payload,
    build_streak_payload,
    build_week_overview_payload,
)

logger = logging.getLogger(__name__)


def _parse_interval_days(value: str | None) -> int:
    if value in (None, ""):
        return 1
    try:
        interval_days = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid interval_days. Use an integer between 1 and 30.") from exc
    if interval_days < 1 or interval_days > 30:
        raise ValueError("Invalid interval_days. Use an integer between 1 and 30.")
    return interval_days


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
        request_serializer = GenerateDailyTaskListRequestSerializer(data=request.data)
        if not request_serializer.is_valid():
            date_error = request_serializer.errors.get("date")
            mode_error = request_serializer.errors.get("day_mode")
            note_error = request_serializer.errors.get("day_mode_note")
            return Response(
                {
                    "error": (
                        date_error[0]
                        if date_error
                        else mode_error[0]
                        if mode_error
                        else note_error[0]
                        if note_error
                        else "Invalid request data."
                    )
                },
                status=http_status.HTTP_400_BAD_REQUEST,
            )
        validated = request_serializer.validated_data
        target_date = validated.get("date", timezone.localdate())
        force = validated.get("force", False)
        day_mode = validated.get("day_mode")
        day_mode_note = validated.get("day_mode_note", "")

        task_list, created = get_or_create_today_task_list(
            request.user,
            target_date,
            force_regenerate=force,
            day_mode=day_mode,
            day_mode_note=day_mode_note,
        )
        serializer = DailyTaskListSerializer(task_list, context={"request": request})
        message = (
            "Daily task list generated."
            if created
            else f"Task list already exists for {target_date}."
        )
        response_status = http_status.HTTP_201_CREATED if created else http_status.HTTP_200_OK
        return Response({"message": message, "task_list": serializer.data}, status=response_status)


class RoutineDetailAPIView(APIView):
    """
    DELETE /routines/<routine_id>/
    Deletes a specific daily routine list if owned by the requesting user.
    """

    permission_classes = [IsAuthenticated]

    def delete(self, request, routine_id):
        routine = DailyTaskList.objects.filter(id=routine_id).first()
        if not routine:
            return Response({"error": "Routine not found."}, status=http_status.HTTP_404_NOT_FOUND)
        if routine.user_id != request.user.id:
            return Response(
                {"error": "You do not have permission to delete this routine."},
                status=http_status.HTTP_403_FORBIDDEN,
            )

        routine.delete()
        return Response(status=http_status.HTTP_204_NO_CONTENT)


class RoutineTaskReorderAPIView(APIView):
    """
    PATCH /routines/<routine_id>/reorder/
    Body: { "task_ids": ["<task_uuid>", ...] }
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request, routine_id):
        request_serializer = ReorderRoutineTasksRequestSerializer(data=request.data)
        if not request_serializer.is_valid():
            return Response(request_serializer.errors, status=http_status.HTTP_400_BAD_REQUEST)

        routine = DailyTaskList.objects.filter(id=routine_id).first()
        if not routine:
            return Response({"error": "Routine not found."}, status=http_status.HTTP_404_NOT_FOUND)
        if routine.user_id != request.user.id:
            return Response(
                {"error": "You do not have permission to reorder tasks in this routine."},
                status=http_status.HTTP_403_FORBIDDEN,
            )

        ordered_task_ids = [str(task_id) for task_id in request_serializer.validated_data["task_ids"]]
        if len(ordered_task_ids) != len(set(ordered_task_ids)):
            return Response(
                {"error": "task_ids contains duplicate values."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        routine_tasks = list(
            DailyTaskItem.objects.filter(task_list=routine, removed_by_user=False)
        )
        existing_ids = [str(task.id) for task in routine_tasks]
        if set(ordered_task_ids) != set(existing_ids) or len(ordered_task_ids) != len(existing_ids):
            return Response(
                {"error": "task_ids must include each routine task id exactly once."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        tasks_by_id = {str(task.id): task for task in routine_tasks}
        with transaction.atomic():
            tasks_to_update = []
            for order, task_id in enumerate(ordered_task_ids):
                task = tasks_by_id[task_id]
                if task.display_order != order:
                    task.display_order = order
                    tasks_to_update.append(task)
            if tasks_to_update:
                DailyTaskItem.objects.bulk_update(tasks_to_update, ["display_order"])

        ordered_tasks = (
            DailyTaskItem.objects.filter(task_list=routine, removed_by_user=False)
            .select_related("related_goal", "habit", "event")
            .order_by("display_order", "created_at")
        )
        return Response(
            {
                "message": "Routine tasks reordered successfully.",
                "tasks": DailyTaskItemSerializer(ordered_tasks, many=True).data,
            },
            status=http_status.HTTP_200_OK,
        )


class RoutineTaskListCreateAPIView(APIView):
    """
    POST /routines/<routine_id>/tasks/
    Create a manual task directly within an existing routine list.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, routine_id):
        request_serializer = CreateRoutineTaskRequestSerializer(data=request.data)
        if not request_serializer.is_valid():
            return Response(request_serializer.errors, status=http_status.HTTP_400_BAD_REQUEST)

        routine = DailyTaskList.objects.filter(id=routine_id).first()
        if not routine:
            return Response({"error": "Routine not found."}, status=http_status.HTTP_404_NOT_FOUND)
        if routine.user_id != request.user.id:
            return Response(
                {"error": "You do not have permission to add tasks to this routine."},
                status=http_status.HTTP_403_FORBIDDEN,
            )

        max_order = DailyTaskItem.objects.filter(task_list=routine).aggregate(
            models.Max("display_order")
        )["display_order__max"]
        if max_order is None:
            max_order = -1
        validated = request_serializer.validated_data
        fit_result = validate_manual_task_schedule_fit(
            task_list=routine,
            estimated_minutes=validated.get("estimated_minutes", 30),
            time_slot=validated.get("time_slot"),
            suggested_time=validated.get("suggested_time"),
        )
        if not fit_result["ok"]:
            return Response(
                {
                    "error": fit_result["error"],
                    "code": fit_result["code"],
                    "details": fit_result["details"],
                },
                status=http_status.HTTP_400_BAD_REQUEST,
            )
        task_item = DailyTaskItem.objects.create(
            task_list=routine,
            item_type="manual_task",
            title=validated["title"],
            description=validated.get("description", ""),
            icon=validated.get("icon", "✅"),
            priority=validated.get("priority", "medium"),
            estimated_minutes=validated.get("estimated_minutes", 30),
            time_slot=validated.get("time_slot"),
            suggested_time=validated.get("suggested_time"),
            why_important=validated.get("why_important", ""),
            display_order=max_order + 1,
        )
        routine.update_progress()
        return Response(
            {
                "message": "Task created successfully.",
                "task": DailyTaskItemSerializer(task_item).data,
            },
            status=http_status.HTTP_201_CREATED,
        )


class RoutineTaskDetailAPIView(APIView):
    """
    PATCH /routines/tasks/<task_id>/
    DELETE /routines/tasks/<task_id>/
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request, task_id):
        request_serializer = UpdateRoutineTaskRequestSerializer(data=request.data, partial=True)
        if not request_serializer.is_valid():
            return Response(request_serializer.errors, status=http_status.HTTP_400_BAD_REQUEST)

        task_item = DailyTaskItem.objects.filter(id=task_id).select_related("task_list").first()
        if not task_item:
            return Response({"error": "Task not found."}, status=http_status.HTTP_404_NOT_FOUND)
        if task_item.task_list.user_id != request.user.id:
            return Response(
                {"error": "You do not have permission to edit this task."},
                status=http_status.HTTP_403_FORBIDDEN,
            )

        updated_values = dict(request_serializer.validated_data)
        fit_result = validate_manual_task_schedule_fit(
            task_list=task_item.task_list,
            estimated_minutes=updated_values.get("estimated_minutes", task_item.estimated_minutes),
            time_slot=updated_values.get("time_slot", task_item.time_slot),
            suggested_time=updated_values.get("suggested_time", task_item.suggested_time),
            exclude_task_id=task_item.id,
        )
        if not fit_result["ok"]:
            return Response(
                {
                    "error": fit_result["error"],
                    "code": fit_result["code"],
                    "details": fit_result["details"],
                },
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        for field, value in updated_values.items():
            setattr(task_item, field, value)
        task_item.save()

        return Response(
            {
                "message": "Task updated successfully.",
                "task": DailyTaskItemSerializer(task_item).data,
            },
            status=http_status.HTTP_200_OK,
        )

    def delete(self, request, task_id):
        task_item = DailyTaskItem.objects.filter(id=task_id).select_related("task_list").first()
        if not task_item:
            return Response({"error": "Task not found."}, status=http_status.HTTP_404_NOT_FOUND)
        if task_item.task_list.user_id != request.user.id:
            return Response(
                {"error": "You do not have permission to delete this task."},
                status=http_status.HTTP_403_FORBIDDEN,
            )

        task_list = task_item.task_list
        task_item.delete()
        if task_list.tasks.exists():
            task_list.update_progress()
        else:
            task_list.total_tasks = 0
            task_list.completed_tasks = 0
            task_list.completion_percentage = 0
            task_list.is_fully_completed = False
            task_list.status = "pending"
            task_list.completed_at = None
            task_list.completed_on_time = False
            task_list.save(
                update_fields=[
                    "total_tasks",
                    "completed_tasks",
                    "completion_percentage",
                    "is_fully_completed",
                    "status",
                    "completed_at",
                    "completed_on_time",
                    "updated_at",
                ]
            )

        return Response({"message": "Task deleted successfully."}, status=http_status.HTTP_200_OK)


class RoutineTaskRemoveAPIView(APIView):
    """
    POST /routines/tasks/<task_id>/remove/
    Soft-remove generated routine tasks from active views.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, task_id):
        task_item = get_object_or_404(
            DailyTaskItem.objects.select_related("task_list"),
            id=task_id,
            task_list__user=request.user,
        )
        if not task_item.is_generated_routine_item:
            return Response(
                {"error": "Only generated routine tasks can be removed."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )
        if task_item.removed_by_user:
            return Response(
                {
                    "message": "Task already removed.",
                    "task": DailyTaskItemSerializer(task_item).data,
                },
                status=http_status.HTTP_200_OK,
            )

        task_item.removed_by_user = True
        task_item.removed_at = timezone.now()
        task_item.save(update_fields=["removed_by_user", "removed_at", "updated_at"])
        task_item.task_list.update_progress()

        return Response(
            {
                "message": "Task removed successfully.",
                "task": DailyTaskItemSerializer(task_item).data,
            },
            status=http_status.HTTP_200_OK,
        )


class RoutineTaskRestoreAPIView(APIView):
    """
    POST /routines/tasks/<task_id>/restore/
    Restore previously soft-removed generated routine tasks.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, task_id):
        task_item = get_object_or_404(
            DailyTaskItem.objects.select_related("task_list"),
            id=task_id,
            task_list__user=request.user,
        )
        if not task_item.is_generated_routine_item:
            return Response(
                {"error": "Only generated routine tasks can be restored."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )
        if not task_item.removed_by_user:
            return Response(
                {
                    "message": "Task is already active.",
                    "task": DailyTaskItemSerializer(task_item).data,
                },
                status=http_status.HTTP_200_OK,
            )

        task_item.removed_by_user = False
        task_item.removed_at = None
        task_item.save(update_fields=["removed_by_user", "removed_at", "updated_at"])
        task_item.task_list.update_progress()

        return Response(
            {
                "message": "Task restored successfully.",
                "task": DailyTaskItemSerializer(task_item).data,
            },
            status=http_status.HTTP_200_OK,
        )


class CompleteTaskItemAPIView(APIView):
    """
    POST /api/routines/tasks/<task_id>/complete/
    Body: { "notes": "...", "actual_minutes": 45 }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, task_id):
        request_serializer = CompleteTaskItemRequestSerializer(data=request.data)
        if not request_serializer.is_valid():
            return Response(request_serializer.errors, status=http_status.HTTP_400_BAD_REQUEST)

        task_item = get_object_or_404(
            DailyTaskItem,
            id=task_id,
            task_list__user=request.user,
            removed_by_user=False,
        )

        if task_item.is_completed:
            return Response(
                {"message": "Task already completed."},
                status=http_status.HTTP_200_OK,
            )

        task_item.mark_completed(
            notes=request_serializer.validated_data.get("notes", ""),
            actual_minutes=request_serializer.validated_data.get("actual_minutes"),
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
        request_serializer = SkipTaskItemRequestSerializer(data=request.data)
        if not request_serializer.is_valid():
            return Response(request_serializer.errors, status=http_status.HTTP_400_BAD_REQUEST)

        task_item = get_object_or_404(
            DailyTaskItem,
            id=task_id,
            task_list__user=request.user,
            removed_by_user=False,
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

        task_item.mark_skipped(reason=request_serializer.validated_data.get("reason", ""))
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
        week_data = build_week_overview_payload(request.user)
        return Response(week_data, status=http_status.HTTP_200_OK)


class ProgressOverviewAPIView(APIView):
    """
    GET /api/routines/progress/?period=week|month|year|all
    Returns a complete progress report payload for the frontend progress page.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        period = request.query_params.get("period", "week").lower()
        selected_date_str = request.query_params.get("date")
        interval_days_str = request.query_params.get("streak_interval_days")

        try:
            streak_interval_days = _parse_interval_days(interval_days_str)
            payload = build_progress_overview_payload(
                user=request.user,
                period=period,
                selected_date_str=selected_date_str,
                streak_interval_days=streak_interval_days,
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)

        return Response(payload, status=http_status.HTTP_200_OK)


class GoalProgressView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, goal_id):
        goal = get_object_or_404(Goal, id=goal_id, user=request.user)
        serializer = GoalProgressEntrySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        validated = serializer.validated_data
        entry_date = validated.get('date', timezone.localdate())
        metric_name = validated['metric_name']

        entry, created = GoalProgressEntry.objects.update_or_create(
            goal=goal,
            user=request.user,
            date=entry_date,
            metric_name=metric_name,
            defaults={
                'metric_value': validated['metric_value'],
                'metric_unit': validated['metric_unit'],
                'metric_direction': validated.get('metric_direction', 'up'),
                'domain': validated.get('domain', 'physical'),
                'metric_start': validated['metric_start'],
                'metric_target': validated['metric_target'],
                'note': validated.get('note', ''),
            },
        )

        return Response(
            {
                'message': 'Progress entry created.' if created else 'Progress entry updated.',
                'entry': GoalProgressEntrySerializer(entry).data,
            },
            status=http_status.HTTP_201_CREATED if created else http_status.HTTP_200_OK,
        )

    def get(self, request, goal_id):
        goal = get_object_or_404(Goal, id=goal_id, user=request.user)
        entries = GoalProgressEntry.objects.filter(
            user=request.user,
            goal=goal,
        ).order_by('date')
        return Response(
            {'entries': GoalProgressEntrySerializer(entries, many=True).data},
            status=http_status.HTTP_200_OK,
        )


class ProgressDashboardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        entries = list(
            GoalProgressEntry.objects.filter(user=request.user)
            .select_related('goal')
            .order_by('goal_id', 'metric_name', 'date')
        )

        grouped = defaultdict(list)
        series_by_key = defaultdict(list)
        for entry in entries:
            key = (entry.goal_id, entry.metric_name)
            series_by_key[key].append(entry)

        for series in series_by_key.values():
            start_entry = series[0]
            latest_entry = series[-1]
            sparkline_entries = series[-7:]
            metric_payload = {
                'goal_id': str(latest_entry.goal_id),
                'goal_title': latest_entry.goal.title,
                'metric_name': latest_entry.metric_name,
                'metric_unit': latest_entry.metric_unit,
                'metric_direction': latest_entry.metric_direction,
                'start_value': start_entry.metric_value,
                'current_value': latest_entry.metric_value,
                'target_value': latest_entry.metric_target,
                'progress_percentage': latest_entry.progress_percentage,
                'sparkline': [
                    {
                        'date': item.date.isoformat(),
                        'value': item.metric_value,
                    }
                    for item in sparkline_entries
                ],
            }
            grouped[latest_entry.domain].append(metric_payload)

        for domain in grouped:
            grouped[domain].sort(key=lambda item: (item['goal_title'], item['metric_name']))

        return Response(
            {
                'dashboard': {
                    'physical': grouped.get('physical', []),
                    'mental': grouped.get('mental', []),
                    'lifestyle': grouped.get('lifestyle', []),
                }
            },
            status=http_status.HTTP_200_OK,
        )


class DailyBriefView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        brief = get_or_generate_today_brief(request.user)
        return Response(
            {"brief": DailyBriefSerializer(brief).data},
            status=http_status.HTTP_200_OK,
        )


class TrackStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        request_serializer = TrackStatusRequestSerializer(data=request.data)
        if not request_serializer.is_valid():
            return Response(request_serializer.errors, status=http_status.HTTP_400_BAD_REQUEST)

        brief = get_or_generate_today_brief(request.user)
        brief.set_track_status(request_serializer.validated_data["status"])
        return Response(
            {"brief": DailyBriefSerializer(brief).data},
            status=http_status.HTTP_200_OK,
        )


class DisciplineStreakAPIView(APIView):
    """GET /api/routines/streak/"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            interval_days = _parse_interval_days(request.query_params.get("interval_days"))
        except ValueError as exc:
            return Response({"error": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)
        payload = build_streak_payload(request.user, interval_days=interval_days)
        return Response(payload, status=http_status.HTTP_200_OK)


class HabitTrackerAPIView(APIView):
    """
    GET  /api/routines/habits/
    POST /api/routines/habits/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        seed_system_habits_for_user(request.user)
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
    PATCH  /api/routines/habits/<habit_id>/
    DELETE /api/routines/habits/<habit_id>/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, habit_id):
        seed_system_habits_for_user(request.user)
        habit = get_object_or_404(HabitTracker, id=habit_id, user=request.user)
        return Response(
            {"habit": HabitTrackerSerializer(habit).data},
            status=http_status.HTTP_200_OK,
        )

    def put(self, request, habit_id):
        habit = get_object_or_404(HabitTracker, id=habit_id, user=request.user)
        if habit.is_system:
            return Response(
                {
                    "error": "System habits cannot be fully edited. Use PATCH to update allowed fields only."
                },
                status=http_status.HTTP_403_FORBIDDEN,
            )
        serializer = HabitTrackerSerializer(habit, data=request.data, partial=True)
        if serializer.is_valid():
            try:
                serializer.save()
            except ValidationError as exc:
                detail = exc.message_dict if hasattr(exc, "message_dict") else {"error": exc.messages[0]}
                return Response(detail, status=http_status.HTTP_403_FORBIDDEN)
            return Response(serializer.data, status=http_status.HTTP_200_OK)
        return Response(serializer.errors, status=http_status.HTTP_400_BAD_REQUEST)

    def patch(self, request, habit_id):
        habit = get_object_or_404(HabitTracker, id=habit_id, user=request.user)

        if habit.is_system:
            allowed_fields = {"estimated_minutes", "suggested_time", "time_slot"}
            disallowed = set(request.data.keys()) - allowed_fields

            if disallowed:
                return Response(
                    {
                        "error": "Only estimated_minutes, suggested_time, and time_slot can be updated on system habits.",
                        "disallowed_fields": sorted(disallowed),
                    },
                    status=http_status.HTTP_403_FORBIDDEN,
                )

            filtered_data = {
                key: value for key, value in request.data.items()
                if key in allowed_fields
            }
            serializer = HabitTrackerSerializer(habit, data=filtered_data, partial=True)
            serializer.is_valid(raise_exception=True)
            try:
                serializer.save()
            except ValidationError as exc:
                detail = exc.message_dict if hasattr(exc, "message_dict") else {"error": exc.messages[0]}
                return Response(detail, status=http_status.HTTP_403_FORBIDDEN)
            return Response(serializer.data, status=http_status.HTTP_200_OK)

        serializer = HabitTrackerSerializer(habit, data=request.data, partial=True)
        if serializer.is_valid():
            try:
                serializer.save()
            except ValidationError as exc:
                detail = exc.message_dict if hasattr(exc, "message_dict") else {"error": exc.messages[0]}
                return Response(detail, status=http_status.HTTP_403_FORBIDDEN)
            return Response(serializer.data, status=http_status.HTTP_200_OK)
        return Response(serializer.errors, status=http_status.HTTP_400_BAD_REQUEST)

    def delete(self, request, habit_id):
        habit = get_object_or_404(HabitTracker, id=habit_id, user=request.user)
        if habit.is_system:
            return Response(
                {"error": "System habits cannot be deleted."},
                status=http_status.HTTP_403_FORBIDDEN,
            )
        try:
            habit.delete()
        except ValidationError as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else {"error": exc.messages[0]}
            return Response(detail, status=http_status.HTTP_403_FORBIDDEN)
        return Response(status=http_status.HTTP_204_NO_CONTENT)


class HealthProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profiles = list(
            HealthProfile.objects.filter(user=request.user).order_by("-updated_at", "-created_at")
        )
        if not profiles:
            return Response({"error": "Health profile not found."}, status=http_status.HTTP_404_NOT_FOUND)
        serializer = HealthProfileSerializer(profiles, many=True)
        active_profile = next((profile for profile in profiles if profile.is_active), profiles[0])
        return Response(
            {
                "health_profiles": serializer.data,
                "health_profile": HealthProfileSerializer(active_profile).data,
            },
            status=http_status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = HealthProfileSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(user=request.user)
            return Response({"health_profile": serializer.data}, status=http_status.HTTP_201_CREATED)
        return Response(serializer.errors, status=http_status.HTTP_400_BAD_REQUEST)

    def patch(self, request):
        profiles = list(
            HealthProfile.objects.filter(user=request.user).order_by("-updated_at", "-created_at")
        )
        if not profiles:
            return Response({"error": "Health profile not found."}, status=http_status.HTTP_404_NOT_FOUND)
        if len(profiles) > 1:
            return Response(
                {"error": "Multiple health profiles exist. Use the detail endpoint to update a specific profile."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )
        profile = profiles[0]
        serializer = HealthProfileSerializer(profile, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({"health_profile": serializer.data}, status=http_status.HTTP_200_OK)
        return Response(serializer.errors, status=http_status.HTTP_400_BAD_REQUEST)


class HealthProfileDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, profile_id):
        profile = get_object_or_404(HealthProfile, id=profile_id, user=request.user)
        serializer = HealthProfileSerializer(profile)
        return Response({"health_profile": serializer.data}, status=http_status.HTTP_200_OK)

    def patch(self, request, profile_id):
        profile = get_object_or_404(HealthProfile, id=profile_id, user=request.user)
        serializer = HealthProfileSerializer(profile, data=request.data, partial=True)
        if serializer.is_valid():
            updated_profile = serializer.save()
            if serializer.validated_data.get("is_active") is True:
                updated_profile = activate_profile(user=request.user, profile=updated_profile)
            return Response(
                {"health_profile": HealthProfileSerializer(updated_profile).data},
                status=http_status.HTTP_200_OK,
            )
        return Response(serializer.errors, status=http_status.HTTP_400_BAD_REQUEST)

    def delete(self, request, profile_id):
        profile = get_object_or_404(HealthProfile, id=profile_id, user=request.user)
        profile.delete()
        return Response(status=http_status.HTTP_204_NO_CONTENT)


class HabitSuggestView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        request_serializer = HabitSuggestionRequestSerializer(data=request.data)
        if not request_serializer.is_valid():
            return Response(request_serializer.errors, status=http_status.HTTP_400_BAD_REQUEST)

        try:
            recommendations = generate_habit_recommendations_for_user(
                user=request.user,
                goal_id=str(request_serializer.validated_data.get("goal_id")) if request_serializer.validated_data.get("goal_id") else None,
                profile_id=str(request_serializer.validated_data.get("profile_id")) if request_serializer.validated_data.get("profile_id") else None,
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=http_status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            logger.exception("Habit suggestion generation failed for user %s", request.user.id)
            return Response({"error": str(exc)}, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)

        serializer = HabitRecommendationSerializer(recommendations, many=True)
        return Response({"suggestions": serializer.data}, status=http_status.HTTP_201_CREATED)


class HabitSuggestionListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        status_filter = request.query_params.get("status")
        profile_id = request.query_params.get("profile_id")
        queryset = request.user.habit_recommendations.all()
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        if profile_id:
            queryset = queryset.filter(source_health_profile_id=profile_id)
        serializer = HabitRecommendationSerializer(queryset, many=True)
        return Response({"suggestions": serializer.data}, status=http_status.HTTP_200_OK)


class HabitSuggestionAcceptView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, suggestion_id):
        recommendation = get_object_or_404(
            request.user.habit_recommendations,
            id=suggestion_id,
        )
        habit = recommendation.accept()
        return Response(
            {
                "suggestion": HabitRecommendationSerializer(recommendation).data,
                "habit": HabitTrackerSerializer(habit).data,
            },
            status=http_status.HTTP_200_OK,
        )


class HabitSuggestionRejectView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, suggestion_id):
        recommendation = get_object_or_404(
            request.user.habit_recommendations,
            id=suggestion_id,
        )
        recommendation.reject()
        return Response({"suggestion": HabitRecommendationSerializer(recommendation).data}, status=http_status.HTTP_200_OK)


class HabitSuggestionSnoozeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, suggestion_id):
        request_serializer = HabitSuggestionSnoozeRequestSerializer(data=request.data)
        if not request_serializer.is_valid():
            return Response(request_serializer.errors, status=http_status.HTTP_400_BAD_REQUEST)
        recommendation = get_object_or_404(
            request.user.habit_recommendations,
            id=suggestion_id,
        )
        recommendation.snooze(request_serializer.validated_data["until_date"])
        return Response({"suggestion": HabitRecommendationSerializer(recommendation).data}, status=http_status.HTTP_200_OK)

