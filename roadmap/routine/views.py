#==============================================================================
# roadmap/routine/views.py
# ==============================================================================
import logging
from collections import defaultdict

from django.shortcuts import get_object_or_404
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
)
from routine.daily_brief_service import get_or_generate_today_brief
from routine.habit_recommendation_service import generate_habit_recommendations_for_user
from routine.services import get_or_create_today_task_list, update_discipline_streak
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
            return Response(
                {"error": date_error[0] if date_error else "Invalid request data."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )
        validated = request_serializer.validated_data
        target_date = validated.get("date", timezone.localdate())
        force = validated.get("force", False)

        task_list, created = get_or_create_today_task_list(
            request.user, target_date, force_regenerate=force
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
            DailyTaskItem, id=task_id, task_list__user=request.user
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


class HealthProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profiles = list(
            HealthProfile.objects.filter(user=request.user).order_by("-updated_at", "-created_at")
        )
        if not profiles:
            return Response({"error": "Health profile not found."}, status=http_status.HTTP_404_NOT_FOUND)
        serializer = HealthProfileSerializer(profiles, many=True)
        return Response(
            {
                "health_profiles": serializer.data,
                "health_profile": serializer.data[0],  # backward compatibility
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
        profile = (
            HealthProfile.objects.filter(user=request.user).order_by("-updated_at", "-created_at").first()
        )
        if not profile:
            return Response({"error": "Health profile not found."}, status=http_status.HTTP_404_NOT_FOUND)
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
            serializer.save()
            return Response({"health_profile": serializer.data}, status=http_status.HTTP_200_OK)
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

