import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.db.models import Avg, Count, Q
from django.utils import timezone

from goal.models import Goal
from rituals.engine import (
    TRIGGER_WEB_BUTTON_CLICKED,
    clean_message_for_tts,
    trigger_ritual_message,
)
from routine.models import DailyTaskItem, DailyTaskList, DisciplineStreak
from routine.services import get_or_create_today_task_list


INTENT_GET_NEXT_TASK = "GET_NEXT_TASK"
INTENT_GET_TODAY_ROUTINE = "GET_TODAY_ROUTINE"
INTENT_GET_PROGRESS_SUMMARY = "GET_PROGRESS_SUMMARY"
INTENT_PLAY_RITUAL_MESSAGE = "PLAY_RITUAL_MESSAGE"
INTENT_OPEN_GOALS = "OPEN_GOALS"
INTENT_OPEN_JOURNAL = "OPEN_JOURNAL"
INTENT_UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class AssistantResult:
    reply: str
    intent: str
    speak: bool = True
    action: dict[str, Any] | None = None

    def as_payload(self) -> dict[str, Any]:
        return {
            "reply": self.reply,
            "intent": self.intent,
            "speak": self.speak,
            "action": self.action,
        }


def normalize_message(message: str) -> str:
    normalized = re.sub(r"[^a-z0-9\s']", " ", (message or "").lower())
    return re.sub(r"\s+", " ", normalized).strip()


def _has_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def detect_intent(message: str) -> str:
    text = normalize_message(message)

    if _has_any(text, ("open my goals", "show goals", "open goals", "goals page")):
        return INTENT_OPEN_GOALS
    if _has_any(text, ("open my journal", "open journal", "show journal", "journal page")):
        return INTENT_OPEN_JOURNAL
    if _has_any(text, ("ritual", "read today", "read my message", "play my message")):
        return INTENT_PLAY_RITUAL_MESSAGE
    if _has_any(text, ("next task", "do now", "what should i do", "what do i do next")):
        return INTENT_GET_NEXT_TASK
    if _has_any(text, ("today's routine", "todays routine", "today's plan", "todays plan", "show routine", "daily routine")):
        return INTENT_GET_TODAY_ROUTINE
    if _has_any(text, ("progress", "how am i doing", "how'm i doing", "doing so far", "summary")):
        return INTENT_GET_PROGRESS_SUMMARY

    return INTENT_UNKNOWN


def _get_next_task_reply(user) -> str:
    today = timezone.localdate()
    task_list, _ = get_or_create_today_task_list(user, today)
    next_task = (
        DailyTaskItem.objects.filter(
            task_list=task_list,
            removed_by_user=False,
            is_completed=False,
            is_skipped=False,
        )
        .select_related("related_goal", "habit", "event")
        .order_by("display_order", "created_at")
        .first()
    )
    if not next_task:
        return "You do not have an open routine task for today. A quick journal check-in would be a good next move."
    return f"Your next task is {next_task.title}. Start there and keep it simple."


def _get_today_routine_reply(user) -> str:
    today = timezone.localdate()
    task_list, _ = get_or_create_today_task_list(user, today)
    tasks = list(
        DailyTaskItem.objects.filter(task_list=task_list, removed_by_user=False)
        .order_by("display_order", "created_at")
        .values_list("title", "is_completed")[:5]
    )
    if not tasks:
        return "Your routine is clear for today. Use the routine page if you want to add a focused task."

    open_count = sum(1 for _, is_completed in tasks if not is_completed)
    task_names = ", ".join(title for title, _ in tasks[:3])
    return f"Today's routine has {task_list.total_tasks} tasks, with {open_count} still open in the first set. First up: {task_names}."


def _get_progress_reply(user) -> str:
    goals = Goal.objects.filter(user=user)
    goal_counts = goals.aggregate(
        total=Count("id"),
        completed=Count("id", filter=Q(status="completed")),
        average_progress=Avg("progress_percentage"),
    )
    routine_rows = DailyTaskList.objects.filter(
        user=user,
        date__gte=timezone.localdate() - timedelta(days=6),
    )
    routine_average = routine_rows.aggregate(value=Avg("completion_percentage"))["value"]
    streak = DisciplineStreak.objects.filter(user=user).first()

    active_goals = goals.exclude(status__in=["completed", "cancelled"]).count()
    avg_goal_progress = int(goal_counts["average_progress"] or 0)
    avg_routine = int(routine_average or 0)
    streak_days = streak.current_streak_days if streak else 0

    return (
        f"You have {active_goals} active goals, average goal progress is {avg_goal_progress} percent, "
        f"and your seven day routine average is {avg_routine} percent. Current discipline streak: {streak_days} days."
    )


def _get_ritual_reply(user, header_timezone: str | None) -> str:
    payload = trigger_ritual_message(
        user,
        TRIGGER_WEB_BUTTON_CLICKED,
        header_timezone=header_timezone,
    )
    message = clean_message_for_tts(payload.get("message", ""))
    return message or "I could not find a ritual message to play right now."


def build_assistant_response(user, message: str, *, mode: str = "chat", header_timezone: str | None = None) -> AssistantResult:
    intent = detect_intent(message)

    if intent == INTENT_GET_NEXT_TASK:
        return AssistantResult(reply=_get_next_task_reply(user), intent=intent, speak=mode == "voice")
    if intent == INTENT_GET_TODAY_ROUTINE:
        return AssistantResult(reply=_get_today_routine_reply(user), intent=intent, speak=mode == "voice")
    if intent == INTENT_GET_PROGRESS_SUMMARY:
        return AssistantResult(reply=_get_progress_reply(user), intent=intent, speak=mode == "voice")
    if intent == INTENT_PLAY_RITUAL_MESSAGE:
        return AssistantResult(reply=_get_ritual_reply(user, header_timezone), intent=intent, speak=True)
    if intent == INTENT_OPEN_GOALS:
        return AssistantResult(
            reply="Opening your goals.",
            intent=intent,
            speak=mode == "voice",
            action={"type": "navigate", "path": "/goals"},
        )
    if intent == INTENT_OPEN_JOURNAL:
        return AssistantResult(
            reply="Opening your journal.",
            intent=intent,
            speak=mode == "voice",
            action={"type": "navigate", "path": "/journal"},
        )

    return AssistantResult(
        reply="I can help with your next task, today's routine, progress, ritual message, goals, or journal.",
        intent=INTENT_UNKNOWN,
        speak=mode == "voice",
    )
