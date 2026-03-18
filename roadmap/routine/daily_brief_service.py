from __future__ import annotations

from django.apps import apps
from django.utils import timezone

from routine.models import DailyBrief, DailyTaskList, GoalProgressEntry, DisciplineStreak, HealthProfile


def _format_goal_metric(goal_metrics_snapshot: dict) -> str:
    metric_candidates: list[tuple[str, str]] = []
    for metrics in goal_metrics_snapshot.values():
        for metric_name, payload in metrics.items():
            goal_title = payload.get("goal_title", "your goal")
            value = payload.get("value")
            unit = payload.get("unit", "")
            progress = payload.get("progress_percentage")
            value_text = f"{value}{unit}" if value not in (None, "") else "an update"
            metric_candidates.append(
                (
                    str(goal_title).lower(),
                    f"{goal_title} is at {value_text} on {metric_name} ({progress}% progress).",
                )
            )

    if not metric_candidates:
        return "Keep one measurable goal moving forward today."
    metric_candidates.sort(key=lambda item: item[0])
    return metric_candidates[0][1]


def _format_events(upcoming_events: list[dict]) -> str:
    if not upcoming_events:
        return "Your schedule looks open enough to protect a focused block."

    first_event = upcoming_events[0]
    title = first_event.get("title", "today's first event")
    start_at = str(first_event.get("start_at", ""))
    time_label = start_at[11:16] if len(start_at) >= 16 else "later today"
    if len(upcoming_events) == 1:
        return f"You have {title} at {time_label}, so plan around that anchor."
    return f"You have {title} at {time_label} and {len(upcoming_events) - 1} more event(s), so protect your most important work early."


def _profile_guidance(profile_context: dict) -> str:
    stress_level = profile_context.get("stress_level")
    willpower_level = profile_context.get("willpower_level")
    sleep_pattern = profile_context.get("sleep_pattern")

    if stress_level in {"high", "burnout"}:
        return "Keep the plan lighter than your ambition and favor clean completions."
    if willpower_level == "low":
        return "Use a tiny starting step so momentum does the hard part for you."
    if sleep_pattern == "night_owl":
        return "Give yourself a slower start and protect the block where you usually focus best."
    return "Keep the next action specific and easy to begin."


def _build_brief_text(
    *,
    user,
    today,
    completion_yesterday: float,
    missed_habits: list[str],
    goal_metrics_snapshot: dict,
    upcoming_events: list[dict],
    streak_days: int,
    previous_track_status: str,
    profile_context: dict,
) -> str:
    first_name = (getattr(user, "first_name", "") or "").strip() or "there"
    completion_value = int(round(completion_yesterday))

    track_clause = {
        "on_track": "You marked yourself on track yesterday",
        "behind": "You marked yourself slightly behind yesterday",
        "struggling": "You marked yourself struggling yesterday",
        "not_set": "You have a clean read on the day ahead",
    }.get(previous_track_status, "You have a clean read on the day ahead")

    sentence_one = (
        f"Good morning, {first_name}; yesterday landed at {completion_value}% completion, "
        f"your streak stands at {streak_days} day(s), and {track_clause.lower()}."
    )

    if missed_habits:
        missed_label = ", ".join(sorted(missed_habits)[:2])
        sentence_two = (
            f"Reset around {missed_label} first, and { _format_goal_metric(goal_metrics_snapshot).lower() }"
        )
    else:
        sentence_two = _format_goal_metric(goal_metrics_snapshot)

    sentence_three = f"{_format_events(upcoming_events).rstrip('.')} and {_profile_guidance(profile_context).rstrip('.').lower()}."
    return " ".join(
        sentence.strip()
        for sentence in (sentence_one, sentence_two, sentence_three)
        if sentence.strip()
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

    brief_text = _build_brief_text(
        user=user,
        today=today.isoformat(),
        completion_yesterday=completion_yesterday,
        missed_habits=missed_habits,
        goal_metrics_snapshot=goal_metrics_snapshot,
        upcoming_events=upcoming_events_today,
        streak_days=streak_days,
        previous_track_status=previous_track_status,
        profile_context=profile_context,
    )

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
