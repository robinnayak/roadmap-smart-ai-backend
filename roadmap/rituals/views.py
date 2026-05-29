from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .date_context import get_date_context
from .engine import (
    _get_goal_day_context,
    build_morning_message,
    build_night_closer,
    build_night_intent_confirmed,
    build_night_open,
    build_night_task_response,
    get_goal_tasks_for_user,
    get_or_create_daily_log,
    get_or_create_ritual_profile,
    get_ritual_time_context,
    get_task_for_today,
    clean_message_for_tts,
    mark_morning_completed,
    mark_morning_entry,
    mark_night_completed,
    set_wake_delta_for_log,
    trigger_ritual_message,
)

from .serializers import (
    RitualTriggerSerializer,
    ToneSerializer,
    MorningEnergySerializer,
    NightReflectionSerializer,
    NightIntentSerializer,
    NightCloseSerializer,
    AlarmTimeSerializer,
    SnoozeCountSerializer,
)

class RitualBaseView(APIView):
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _get_profile(user):
        return get_or_create_ritual_profile(user)

    @staticmethod
    def _wants_plain_message(request):
        plain = str(request.query_params.get("plain", "")).strip().lower()
        output_format = str(request.query_params.get("format", "")).strip().lower()
        return plain in {"1", "true", "yes"} or output_format == "tts"

    @staticmethod
    def _time_context(request):
        return get_ritual_time_context(
            request.user,
            header_timezone=request.headers.get("X-User-Timezone"),
        )

    @classmethod
    def _get_local_today_log(cls, request):
        return get_or_create_daily_log(request.user, cls._time_context(request)["local_date"])


class RitualTriggerAPIView(RitualBaseView):
    def post(self, request):
        serializer = RitualTriggerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = trigger_ritual_message(
            request.user,
            serializer.validated_data["trigger_type"],
            header_timezone=request.headers.get("X-User-Timezone"),
        )
        return Response(payload, status=status.HTTP_200_OK)


class MorningMessageAPIView(RitualBaseView):
    def get(self, request):
        profile = self._get_profile(request.user)
        time_ctx = self._time_context(request)
        log = get_or_create_daily_log(request.user, time_ctx["local_date"])
        mark_morning_entry(log, profile.morning_alarm_time)
        payload = build_morning_message(
            request.user,
            {
                "profile": profile,
                "log": log,
                "tone": profile.ritual_tone,
                "date_ctx": get_date_context(log.date),
                "current_date": log.date,
            },
        )
        message = payload["message"]
        if self._wants_plain_message(request):
            message = clean_message_for_tts(message)
        return Response(
            {
                "message": message,
                "task_today": payload["task_today"],
                "tone": profile.ritual_tone,
            },
            status=status.HTTP_200_OK,
        )


class MorningEnergyAPIView(RitualBaseView):
    def post(self, request):
        serializer = MorningEnergySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = self._get_profile(request.user)
        log = self._get_local_today_log(request)
        mark_morning_completed(log, serializer.validated_data["energy"], profile.morning_alarm_time)
        return Response(
            {
                "energy": log.morning_energy,
                "morning_session_completed": log.morning_session_completed,
            },
            status=status.HTTP_200_OK,
        )


class NightOpenAPIView(RitualBaseView):
    def get(self, request):
        profile = self._get_profile(request.user)
        time_ctx = self._time_context(request)
        log = get_or_create_daily_log(request.user, time_ctx["local_date"])
        message = build_night_open(request.user, tone=profile.ritual_tone, current_date=log.date)
        if self._wants_plain_message(request):
            message = clean_message_for_tts(message)
        return Response(
            {
                "message": message,
                "task_today": get_task_for_today(request.user, current_date=log.date),
                "alarm_time": profile.morning_alarm_time.strftime("%H:%M"),
                "tone": profile.ritual_tone,
            },
            status=status.HTTP_200_OK,
        )


class NightReflectionAPIView(RitualBaseView):
    def post(self, request):
        serializer = NightReflectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = self._get_profile(request.user)
        log = self._get_local_today_log(request)
        reflection = serializer.validated_data["status"]
        if reflection in {"done", "partial", "missed"}:
            log.yesterday_task_reflection = reflection
        else:
            log.night_mood = reflection
        log.save(update_fields=["yesterday_task_reflection", "night_mood", "updated_at"])
        message = build_night_task_response(request.user, profile.ritual_tone, reflection, current_date=log.date)
        return Response({"message": message}, status=status.HTTP_200_OK)


class NightIntentAPIView(RitualBaseView):
    def post(self, request):
        serializer = NightIntentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = self._get_profile(request.user)
        log = self._get_local_today_log(request)
        task = serializer.validated_data["task"].strip()
        log.tomorrow_intent = task
        log.save(update_fields=["tomorrow_intent", "updated_at"])
        return Response(
            {"message": build_night_intent_confirmed(profile.ritual_tone, task)},
            status=status.HTTP_200_OK,
        )


class NightCloseAPIView(RitualBaseView):
    def post(self, request):
        serializer = NightCloseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = self._get_profile(request.user)
        log = self._get_local_today_log(request)
        mark_night_completed(log, serializer.validated_data["mood"])
        goal_day_ctx = _get_goal_day_context(request.user, current_date=log.date)
        return Response(
            {
                "message": build_night_closer(
                    profile.ritual_tone,
                    goal_day_ctx["day_number"] or 1,
                    serializer.validated_data["alarm_time"],
                )
            },
            status=status.HTTP_200_OK,
        )


class GoalTasksAPIView(RitualBaseView):
    def get(self, request):
        time_ctx = self._time_context(request)
        return Response(
            {"tasks": get_goal_tasks_for_user(request.user, limit=6, current_date=time_ctx["local_date"])},
            status=status.HTTP_200_OK,
        )


class ToneAPIView(RitualBaseView):
    def get(self, request):
        profile = self._get_profile(request.user)
        return Response({"tone": profile.ritual_tone}, status=status.HTTP_200_OK)

    def post(self, request):
        return self.patch(request)

    def patch(self, request):
        serializer = ToneSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = self._get_profile(request.user)
        profile.ritual_tone = serializer.validated_data["tone"]
        profile.save(update_fields=["ritual_tone", "updated_at"])
        return Response({"tone": profile.ritual_tone}, status=status.HTTP_200_OK)


class RitualStatusAPIView(RitualBaseView):
    def get(self, request):
        profile = self._get_profile(request.user)
        time_ctx = self._time_context(request)
        log = get_or_create_daily_log(request.user, time_ctx["local_date"])
        return Response(
            {
                "time_segment": time_ctx["time_segment"],
                "timezone": time_ctx["timezone"],
                "local_date": time_ctx["local_date"].isoformat(),
                "local_time": time_ctx["local_time"].strftime("%H:%M"),
                "tone": profile.ritual_tone,
                "morning_session_completed": log.morning_session_completed,
                "night_session_completed": log.night_session_completed,
            },
            status=status.HTTP_200_OK,
        )


class AlarmTimeAPIView(RitualBaseView):
    def post(self, request):
        serializer = AlarmTimeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = self._get_profile(request.user)
        if serializer.validated_data["type"] == "morning":
            profile.morning_alarm_time = serializer.validated_data["time"]
        else:
            profile.night_alarm_time = serializer.validated_data["time"]
        profile.save(update_fields=["morning_alarm_time", "night_alarm_time", "updated_at"])
        return Response(
            {
                "type": serializer.validated_data["type"],
                "time": serializer.validated_data["time"].strftime("%H:%M"),
            },
            status=status.HTTP_200_OK,
        )


class SnoozeCountAPIView(RitualBaseView):
    def post(self, request):
        serializer = SnoozeCountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = self._get_profile(request.user)
        log = self._get_local_today_log(request)
        log.snooze_count = serializer.validated_data["count"]
        set_wake_delta_for_log(log, profile.morning_alarm_time)
        log.save(update_fields=["snooze_count", "wake_delta_minutes", "updated_at"])
        return Response({"count": log.snooze_count}, status=status.HTTP_200_OK)
