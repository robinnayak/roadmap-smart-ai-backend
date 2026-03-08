from __future__ import annotations

from django.apps import apps
from django.utils import timezone

from ai.config import get_ollama_model
from ai.providers.ollama_provider import OllamaProvider
from routine.models import DailyBrief, DailyTaskList, GoalProgressEntry, DisciplineStreak, HealthProfile


def _build_brief_prompt(
    user,
    profile_context: dict,
    today,
    completion_yesterday: float,
    missed_habits: list[str],
    goal_metrics_snapshot: dict,
    upcoming_events: list[dict],
    streak_days: int,
    previous_track_status: str,
) -> str:
    first_name = (getattr(user, "first_name", "") or "").strip() or "there"
    return f"""
You are DayOneGoal's personal life coach.
Today: {today}
User: {first_name}
Profile context: {profile_context}
Yesterday completion percentage: {completion_yesterday}
Missed habits yesterday: {missed_habits}
Latest goal metrics: {goal_metrics_snapshot}
Upcoming events today: {upcoming_events}
Current streak days: {streak_days}
Yesterday track status: {previous_track_status}

Write a warm, honest, specific morning brief in exactly 3 sentences.
Do not use markdown or bullet points.
""".strip()


def _fallback_brief_text(today, completion_yesterday: float, streak_days: int) -> str:
    return (
        f"Good morning. It's {today} and yesterday you completed {int(completion_yesterday)}% of your plan. "
        f"Your current streak is {streak_days} day(s), so keep momentum with one focused step at a time today."
    )


def _extract_latest_goal_metrics(user) -> dict:
    metrics: dict[str, dict] = {}
    entries = (
        GoalProgressEntry.objects.filter(user=user)
        .select_related("goal")
        .order_by("goal_id", "metric_name", "-date", "-created_at")
    )
    seen_keys: set[tuple] = set()
    for entry in entries:
        key = (entry.goal_id, entry.metric_name)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        goal_key = str(entry.goal_id)
        metrics.setdefault(goal_key, {})
        metrics[goal_key][entry.metric_name] = {
            "goal_title": entry.goal.title,
            "value": entry.metric_value,
            "unit": entry.metric_unit,
            "direction": entry.metric_direction,
            "progress_percentage": entry.progress_percentage,
            "date": entry.date.isoformat(),
        }
    return metrics


def _extract_upcoming_events_for_today(user, today) -> list[dict]:
    try:
        event_model = apps.get_model("events", "Event")
    except LookupError:
        return []

    events = event_model.objects.filter(
        user=user,
        start_at__date=today,
    ).order_by("start_at")[:10]
    return [
        {
            "title": event.title,
            "start_at": event.start_at.isoformat(),
            "end_at": event.end_at.isoformat(),
            "event_type": event.event_type,
        }
        for event in events
    ]


def get_or_generate_today_brief(user) -> DailyBrief:
    today = timezone.localdate()
    existing = DailyBrief.objects.filter(user=user, date=today).first()
    if existing:
        return existing

    yesterday = today - timezone.timedelta(days=1)
    yesterday_task_list = DailyTaskList.objects.filter(user=user, date=yesterday).first()
    completion_yesterday = float(getattr(yesterday_task_list, "completion_percentage", 0.0) or 0.0)
    missed_habits: list[str] = []
    if yesterday_task_list:
        missed_habits = list(
            yesterday_task_list.tasks.filter(
                item_type="habit",
                is_completed=False,
                removed_by_user=False,
            ).values_list("title", flat=True)
        )

    goal_metrics_snapshot = _extract_latest_goal_metrics(user)
    upcoming_events_today = _extract_upcoming_events_for_today(user, today)
    streak, _ = DisciplineStreak.objects.get_or_create(user=user)
    streak.reconcile_with_daily_history(as_of_date=today)
    streak_days = int(getattr(streak, "current_streak_days", 0) or 0)
    previous_track_status = (
        DailyBrief.objects.filter(user=user, date=yesterday)
        .values_list("track_status", flat=True)
        .first()
        or "not_set"
    )

    profile = (
        HealthProfile.objects.filter(user=user)
        .order_by("-updated_at", "-created_at")
        .first()
    )
    profile_context = profile.as_ai_context() if profile else {}

    prompt = _build_brief_prompt(
        user=user,
        profile_context=profile_context,
        today=today.isoformat(),
        completion_yesterday=completion_yesterday,
        missed_habits=missed_habits,
        goal_metrics_snapshot=goal_metrics_snapshot,
        upcoming_events=upcoming_events_today,
        streak_days=streak_days,
        previous_track_status=previous_track_status,
    )

    brief_text = ""
    try:
        provider = OllamaProvider(
            model=get_ollama_model(),
            temperature=0.5,
            max_tokens=220,
        )
        response = provider.generate_response(
            prompt=prompt,
            system_prompt="You are concise, warm, and realistic.",
        )
        brief_text = (response.content or "").strip()
    except Exception:
        brief_text = ""

    if not brief_text:
        brief_text = _fallback_brief_text(today=today.isoformat(), completion_yesterday=completion_yesterday, streak_days=streak_days)

    return DailyBrief.objects.create(
        user=user,
        date=today,
        brief_text=brief_text,
        habit_completion_yesterday=completion_yesterday,
        missed_habits_yesterday=missed_habits,
        goal_metrics_snapshot=goal_metrics_snapshot,
        upcoming_events_today=upcoming_events_today,
        streak_at_generation=streak_days,
    )
