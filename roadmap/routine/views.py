#==============================================================================
# roadmap/routine/views.py
# ==============================================================================
import logging
from datetime import datetime, timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status as http_status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from routine.models import DailyTaskList, DailyTaskItem, HabitTracker, DisciplineStreak
from routine.serializers import (
    DailyTaskListSerializer, DailyTaskListSummarySerializer,
    DailyTaskItemSerializer, HabitTrackerSerializer, DisciplineStreakSerializer,
)
from routine.services import get_or_create_today_task_list, update_discipline_streak

logger = logging.getLogger(__name__)


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