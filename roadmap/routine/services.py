# ==============================================================================
# roadmap/routine/services.py
# ==============================================================================
"""
Routine selection logic - pure database queries, no AI needed for task picking.
AI is only used to generate the daily motivation + mantra (two short strings).
"""
import logging
from collections import deque
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.utils import IntegrityError

from goal.models import Task
from routine.models import (
    AdaptiveRoadmapState,
    DailyTaskList,
    DailyTaskItem,
    DisciplineStreak,
    HabitTracker,
    RoutineDayModeCheckIn,
)
from routine.wake_service import get_wake_baseline_metadata

logger = logging.getLogger(__name__)

MAX_DAILY_GOAL_TASKS = 15
GOAL_PRIORITY_ORDER = {"high": 3, "medium": 2, "low": 1}
MIN_DAILY_GOAL_TASKS = 5
ADAPTIVE_SCALE_MIN = -3
ADAPTIVE_SCALE_MAX = 3
ADAPTIVE_SCALE_COOLDOWN_DAYS = 2
SLOT_ORDER = ("morning", "afternoon", "evening")
DAY_MODE_FOCUSED = "focused"
DAY_MODE_FLEX = "flex"
SLOT_WINDOWS = {
    "morning": (time(hour=6, minute=0), time(hour=12, minute=0)),
    "afternoon": (time(hour=12, minute=0), time(hour=18, minute=0)),
    "evening": (time(hour=18, minute=0), time(hour=23, minute=59)),
}

FRICTION_REASON_KEYWORDS = {
    "time_pressure": (
        "no time",
        "busy",
        "meeting",
        "schedule",
        "overload",
        "too much",
        "deadline",
        "work",
    ),
    "low_energy": (
        "tired",
        "exhausted",
        "sleep",
        "fatigue",
        "burnout",
        "sick",
        "drained",
        "low energy",
    ),
    "difficulty": (
        "hard",
        "difficult",
        "confused",
        "unclear",
        "complex",
        "stuck",
        "blocked",
    ),
}

BAD_HABIT_SIGNAL_KEYWORDS = {
    "procrastination": ("procrast", "delay", "avoid", "later"),
    "doomscrolling": ("doomscroll", "social media", "instagram", "youtube", "tiktok", "reels"),
    "sleep_disruption": ("late night", "slept late", "overslept", "sleep debt", "poor sleep"),
    "impulsive_distraction": ("distracted", "mindless", "binge", "gaming too much"),
}


def _minutes_to_time(value: int) -> time:
    value = int(max(0, min(1439, value)))
    return time(hour=value // 60, minute=value % 60)


def _clamp_minutes(value: int, slot: str) -> int:
    slot_start, slot_end = SLOT_WINDOWS[slot]
    start_minutes = slot_start.hour * 60 + slot_start.minute
    end_minutes = slot_end.hour * 60 + slot_end.minute
    # Keep room below the slot end to avoid exact-boundary rollover.
    return max(start_minutes, min(end_minutes - 1, value))


def _default_time_for_slot(
    slot: str | None,
    *,
    wake_baseline_minutes: int | None = None,
    use_wake_baseline: bool = False,
):
    mapping = {
        "morning": time(hour=8, minute=0),
        "afternoon": time(hour=14, minute=0),
        "evening": time(hour=19, minute=0),
    }
    if use_wake_baseline and wake_baseline_minutes is not None and slot in SLOT_ORDER:
        # Shift inferred schedule defaults using wake baseline while preserving explicit user-set times.
        morning_anchor = _clamp_minutes(int(wake_baseline_minutes) + 30, "morning")
        shifted_minutes = {
            "morning": morning_anchor,
            "afternoon": _clamp_minutes(morning_anchor + 300, "afternoon"),
            "evening": _clamp_minutes(morning_anchor + 660, "evening"),
        }
        return _minutes_to_time(shifted_minutes[slot])
    return mapping.get(slot or "", None)


def _infer_time_slot_from_text(*values: str, fallback: str = "morning") -> str:
    text = " ".join(v for v in values if isinstance(v, str)).lower()
    if any(word in text for word in ("morning", "am", "breakfast", "wake", "early")):
        return "morning"
    if any(word in text for word in ("evening", "night", "pm", "journal", "reflect")):
        return "evening"
    if any(word in text for word in ("afternoon", "noon", "midday", "lunch")):
        return "afternoon"
    return fallback


def _infer_time_slot_from_datetime(value: datetime | None, fallback: str = "afternoon") -> str:
    if not value:
        return fallback
    hour = value.hour
    if 6 <= hour < 12:
        return "morning"
    if 12 <= hour < 18:
        return "afternoon"
    if 18 <= hour <= 23:
        return "evening"
    return fallback


def _infer_time_slot_from_interval(
    start_at: datetime | None,
    end_at: datetime | None,
    *,
    target_date: date | None = None,
    fallback: str = "afternoon",
) -> str:
    """
    Infer slot by maximum overlap with slot windows.

    This is preferred for long windows (e.g., 09:50-17:00) where start-time-only
    classification is misleading.
    """
    if not start_at:
        return fallback
    if not end_at or end_at <= start_at:
        return _infer_time_slot_from_datetime(start_at, fallback=fallback)

    tz = start_at.tzinfo
    if tz is None:
        return _infer_time_slot_from_datetime(start_at, fallback=fallback)

    anchor_date = target_date or start_at.date()
    slot_overlaps: dict[str, int] = {}
    for slot_name in SLOT_ORDER:
        slot_start_time, slot_end_time = SLOT_WINDOWS[slot_name]
        slot_start = datetime.combine(anchor_date, slot_start_time, tzinfo=tz)
        slot_end = datetime.combine(anchor_date, slot_end_time, tzinfo=tz)
        slot_overlaps[slot_name] = _compute_overlap_minutes(start_at, end_at, slot_start, slot_end)

    best_slot = max(
        SLOT_ORDER,
        key=lambda slot_name: (
            slot_overlaps.get(slot_name, 0),
            -SLOT_ORDER.index(slot_name),
        ),
    )
    if slot_overlaps.get(best_slot, 0) > 0:
        return best_slot

    return _infer_time_slot_from_datetime(start_at, fallback=fallback)


def _slot_duration_minutes(slot_name: str) -> int:
    start_time, end_time = SLOT_WINDOWS[slot_name]
    start_minutes = start_time.hour * 60 + start_time.minute
    end_minutes = end_time.hour * 60 + end_time.minute
    return max(0, end_minutes - start_minutes)


def _datetime_from_date_and_time(target_date: date, target_time: time, tz: ZoneInfo) -> datetime:
    return datetime.combine(target_date, target_time, tzinfo=tz)


def _compute_overlap_minutes(start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime) -> int:
    overlap_start = max(start_a, start_b)
    overlap_end = min(end_a, end_b)
    seconds = (overlap_end - overlap_start).total_seconds()
    return max(0, int(seconds // 60))


def _build_default_schedule_constraints(target_date: date) -> dict:
    return {
        "timezone": "UTC",
        "window_start": f"{target_date.isoformat()}T00:00:00+00:00",
        "window_end": f"{target_date.isoformat()}T23:59:59+00:00",
        "occupied_windows": [],
        "fit_summary": {
            "available_minutes": 0,
            "required_minutes": 0,
            "fit_status": "fit",
            "fallback_strategy": "none",
        },
    }


def _get_event_occurrences_for_day(user, target_date: date) -> list[dict]:
    try:
        from events.models import Event
        from events.services import expand_event_occurrences
    except Exception:
        return []

    events = Event.objects.filter(user=user).order_by("start_at")
    if not events.exists():
        return []

    event_occurrences = []
    for event in events:
        occurrences = expand_event_occurrences(
            event=event,
            start_date=target_date,
            end_date=target_date,
            output_timezone=event.timezone,
        )
        for occurrence in occurrences:
            routine_constraint = occurrence.get("routine_constraint") or {}
            buffer_before = int(routine_constraint.get("buffer_before_minutes", 0))
            buffer_after = int(routine_constraint.get("buffer_after_minutes", 0))
            start_value = occurrence["start_at"]
            end_value = occurrence["end_at"]
            start_dt = (
                start_value
                if isinstance(start_value, datetime)
                else datetime.fromisoformat(str(start_value))
            ) - timedelta(minutes=buffer_before)
            end_dt = (
                end_value
                if isinstance(end_value, datetime)
                else datetime.fromisoformat(str(end_value))
            )
            if end_dt <= start_dt:
                continue
            event_occurrences.append(
                {
                    "event": event,
                    "event_id": occurrence["event_id"],
                    "occurrence_id": occurrence["occurrence_id"],
                    "title": occurrence.get("title", ""),
                    "event_type": occurrence.get("event_type", ""),
                    "start_at": start_dt,
                    "end_at": end_dt,
                    "constraint_mode": routine_constraint.get("constraint_mode", "hard"),
                    "routine_policy": routine_constraint.get("routine_policy", "block"),
                    "buffer_before_minutes": buffer_before,
                    "buffer_after_minutes": buffer_after,
                    "duration_minutes": max(0, int((end_dt - start_dt).total_seconds() // 60)),
                }
            )
    return sorted(
        event_occurrences,
        key=lambda item: (item["start_at"], item["end_at"], item["event_id"]),
    )


def _fetch_day_event_constraints(user, target_date: date, event_occurrences: list[dict] | None = None) -> dict:
    constraints = _build_default_schedule_constraints(target_date)
    event_occurrences = event_occurrences if event_occurrences is not None else _get_event_occurrences_for_day(
        user=user,
        target_date=target_date,
    )
    if not event_occurrences:
        return constraints

    occupied_windows = []
    day_timezone = None
    for occurrence in event_occurrences:
        start_dt = occurrence["start_at"] - timedelta(minutes=int(occurrence.get("buffer_before_minutes", 0)))
        end_dt = occurrence["end_at"] + timedelta(minutes=int(occurrence.get("buffer_after_minutes", 0)))
        if day_timezone is None:
            day_timezone = start_dt.tzinfo
        occupied_windows.append(
            {
                "source": "event",
                "event_id": occurrence["event_id"],
                "occurrence_id": occurrence["occurrence_id"],
                "title": occurrence.get("title", ""),
                "start_at": start_dt,
                "end_at": end_dt,
                "constraint_mode": occurrence.get("constraint_mode", "hard"),
                "routine_policy": occurrence.get("routine_policy", "block"),
            }
        )

    if day_timezone is None:
        return constraints

    constraints["timezone"] = getattr(day_timezone, "key", str(day_timezone))
    day_start = _datetime_from_date_and_time(target_date, time(hour=0, minute=0), day_timezone)
    day_end = _datetime_from_date_and_time(target_date, time(hour=23, minute=59, second=59), day_timezone)
    constraints["window_start"] = day_start.isoformat()
    constraints["window_end"] = day_end.isoformat()
    constraints["occupied_windows"] = occupied_windows
    return constraints


def _build_available_minutes_by_slot(target_date: date, schedule_constraints: dict) -> dict[str, int]:
    timezone_name = schedule_constraints.get("timezone") or "UTC"
    tz = ZoneInfo(timezone_name)
    hard_windows = [
        item
        for item in schedule_constraints.get("occupied_windows", [])
        if item.get("constraint_mode", "hard") == "hard"
    ]

    availability = {}
    for slot_name in SLOT_ORDER:
        slot_start_time, slot_end_time = SLOT_WINDOWS[slot_name]
        slot_start = _datetime_from_date_and_time(target_date, slot_start_time, tz)
        slot_end = _datetime_from_date_and_time(target_date, slot_end_time, tz)
        blocked_minutes = 0
        for window in hard_windows:
            blocked_minutes += _compute_overlap_minutes(slot_start, slot_end, window["start_at"], window["end_at"])
        availability[slot_name] = max(0, _slot_duration_minutes(slot_name) - blocked_minutes)
    return availability


def _select_available_slot(
    preferred_slot: str | None,
    availability_by_slot: dict[str, int],
    *,
    required_minutes: int = 0,
) -> str:
    preferred = preferred_slot if preferred_slot in SLOT_ORDER else "afternoon"
    required = max(0, int(required_minutes or 0))
    if availability_by_slot.get(preferred, 0) >= required and availability_by_slot.get(preferred, 0) > 0:
        return preferred

    ordered_slots = [preferred] + [slot for slot in SLOT_ORDER if slot != preferred]
    for slot_name in ordered_slots:
        if availability_by_slot.get(slot_name, 0) >= required and availability_by_slot.get(slot_name, 0) > 0:
            return slot_name

    for slot_name in ordered_slots:
        if availability_by_slot.get(slot_name, 0) > 0:
            return slot_name
    return preferred


def _reserve_slot_minutes(availability_by_slot: dict[str, int], slot_name: str, minutes: int) -> None:
    if slot_name not in SLOT_ORDER:
        return
    minutes_to_reserve = max(0, int(minutes or 0))
    availability_by_slot[slot_name] = max(
        0,
        int(availability_by_slot.get(slot_name, 0)) - minutes_to_reserve,
    )


def _calculate_required_minutes(habits, goal_tasks, minutes_multiplier: float) -> int:
    habit_minutes = sum(_scale_minutes(h.estimated_minutes, minutes_multiplier) for h in habits)
    goal_minutes = sum(_scale_minutes(t.estimated_duration_minutes, minutes_multiplier) for t in goal_tasks)
    return habit_minutes + goal_minutes


def _apply_overbooked_fallback(
    habits,
    goal_tasks,
    minutes_multiplier: float,
    available_minutes: int,
):
    if available_minutes <= 0:
        return [], [], minutes_multiplier, "partial", 0

    required_minutes = _calculate_required_minutes(habits, goal_tasks, minutes_multiplier)
    if required_minutes <= available_minutes:
        return habits, goal_tasks, minutes_multiplier, "none", required_minutes

    deficit_ratio = (required_minutes - available_minutes) / max(required_minutes, 1)
    if deficit_ratio <= 0.2:
        compressed_multiplier = max(0.7, minutes_multiplier * (available_minutes / required_minutes))
        compressed_required = _calculate_required_minutes(habits, goal_tasks, compressed_multiplier)
        return habits, goal_tasks, compressed_multiplier, "compress", compressed_required

    if deficit_ratio <= 0.5:
        kept_tasks = list(goal_tasks)
        while kept_tasks and _calculate_required_minutes(habits, kept_tasks, minutes_multiplier) > available_minutes:
            drop_index = min(
                range(len(kept_tasks)),
                key=lambda idx: (
                    GOAL_PRIORITY_ORDER.get(kept_tasks[idx].priority, 0),
                    -kept_tasks[idx].display_order,
                    str(kept_tasks[idx].id),
                ),
            )
            kept_tasks.pop(drop_index)
        deferred_required = _calculate_required_minutes(habits, kept_tasks, minutes_multiplier)
        return habits, kept_tasks, minutes_multiplier, "defer", deferred_required

    kept_tasks = sorted(
        goal_tasks,
        key=lambda task: (
            -GOAL_PRIORITY_ORDER.get(task.priority, 0),
            task.display_order,
            str(task.id),
        ),
    )
    limited = []
    for task in kept_tasks:
        candidate = limited + [task]
        if _calculate_required_minutes(habits, candidate, minutes_multiplier) <= available_minutes:
            limited = candidate
    partial_required = _calculate_required_minutes(habits, limited, minutes_multiplier)
    return habits, limited, minutes_multiplier, "partial", partial_required


def _select_balanced_goal_tasks(user, limit: int = MAX_DAILY_GOAL_TASKS) -> list[Task]:
    """
    Pick pending tasks across active goals using balanced round-robin.

    Goal ordering is deterministic:
      1) goal priority (high > medium > low)
      2) goal UUID (string) as tie-breaker

    Task ordering inside each goal is deterministic:
      milestone.display_order -> subgoal.display_order -> task.display_order -> task.id
    """
    goal_tasks_qs = (
        Task.objects.filter(
            subgoal__milestone__goal__user=user,
            subgoal__milestone__goal__status__in=["not_started", "in_progress"],
            status="pending",
        )
        .select_related(
            "subgoal",
            "subgoal__milestone",
            "subgoal__milestone__goal",
        )
        .order_by(
            "subgoal__milestone__display_order",
            "subgoal__display_order",
            "display_order",
            "id",
        )
    )

    if limit <= 0:
        return []

    goals_to_tasks: dict[str, dict] = {}
    for task in goal_tasks_qs:
        goal = task.subgoal.milestone.goal
        goal_id = str(goal.id)
        if goal_id not in goals_to_tasks:
            goals_to_tasks[goal_id] = {"goal": goal, "tasks": deque()}
        goals_to_tasks[goal_id]["tasks"].append(task)

    if not goals_to_tasks:
        return []

    goal_buckets = sorted(
        goals_to_tasks.values(),
        key=lambda bucket: (
            -GOAL_PRIORITY_ORDER.get(bucket["goal"].priority, 0),
            str(bucket["goal"].id),
        ),
    )

    selected: list[Task] = []
    while len(selected) < limit:
        picked_in_cycle = False
        for bucket in goal_buckets:
            if not bucket["tasks"]:
                continue
            selected.append(bucket["tasks"].popleft())
            picked_in_cycle = True
            if len(selected) >= limit:
                break

        if not picked_in_cycle:
            break

    return selected


def _classify_skip_reason(reason: str) -> str:
    text = (reason or "").strip().lower()
    if not text:
        return "other"

    for label, keywords in FRICTION_REASON_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return label
    return "other"


def _shift_priority_down(priority: str) -> str:
    if priority == "high":
        return "medium"
    if priority == "medium":
        return "low"
    return priority


def _scale_minutes(minutes: int | None, multiplier: float) -> int:
    base = minutes or 30
    adjusted = int(round(base * multiplier))
    return max(10, adjusted)


def _append_adjustment_note(base_text: str, note: str) -> str:
    text = (base_text or "").strip()
    if not note:
        return text
    if not text:
        return note
    return f"{text}\n\n{note}"


def _resolve_and_persist_day_mode(user, target_date: date, explicit_day_mode: str | None, day_mode_note: str = "") -> dict:
    note_text = (day_mode_note or "").strip()
    if explicit_day_mode:
        checkin, _ = RoutineDayModeCheckIn.objects.update_or_create(
            user=user,
            date=target_date,
            defaults={
                "day_mode": explicit_day_mode,
                "day_mode_note": note_text,
                "source": "explicit",
            },
        )
        return {
            "day_mode": checkin.day_mode,
            "source": checkin.source,
            "carried_from_date": None,
            "day_mode_note": checkin.day_mode_note,
        }

    existing = RoutineDayModeCheckIn.objects.filter(user=user, date=target_date).first()
    if existing:
        return {
            "day_mode": existing.day_mode,
            "source": existing.source,
            "carried_from_date": None,
            "day_mode_note": existing.day_mode_note,
        }

    prior = (
        RoutineDayModeCheckIn.objects.filter(user=user, date__lt=target_date)
        .order_by("-date", "-created_at")
        .first()
    )
    if prior:
        checkin = RoutineDayModeCheckIn.objects.create(
            user=user,
            date=target_date,
            day_mode=prior.day_mode,
            day_mode_note=prior.day_mode_note,
            source="carry_forward",
        )
        return {
            "day_mode": checkin.day_mode,
            "source": checkin.source,
            "carried_from_date": prior.date.isoformat(),
            "day_mode_note": checkin.day_mode_note,
        }

    checkin = RoutineDayModeCheckIn.objects.create(
        user=user,
        date=target_date,
        day_mode=DAY_MODE_FOCUSED,
        source="default",
    )
    return {
        "day_mode": checkin.day_mode,
        "source": checkin.source,
        "carried_from_date": None,
        "day_mode_note": "",
    }


def _apply_flex_day_profile(habits, goal_tasks, minutes_multiplier: float):
    sorted_habits = sorted(
        habits,
        key=lambda habit: (
            -GOAL_PRIORITY_ORDER.get(habit.priority, 0),
            habit.name.lower(),
            str(habit.id),
        ),
    )
    sorted_goal_tasks = sorted(
        goal_tasks,
        key=lambda task: (
            -GOAL_PRIORITY_ORDER.get(task.priority, 0),
            task.display_order,
            str(task.id),
        ),
    )
    selected_habits = sorted_habits[:1]
    remaining_slots = max(0, 2 - len(selected_habits))
    selected_goal_tasks = sorted_goal_tasks[:remaining_slots]
    if not selected_habits and not selected_goal_tasks and sorted_goal_tasks:
        selected_goal_tasks = sorted_goal_tasks[:1]

    return selected_habits, selected_goal_tasks, max(0.7, minutes_multiplier * 0.75)


def _build_journal_last_task(task_list: DailyTaskList, display_order: int, day_mode: str) -> DailyTaskItem:
    description = "End the day with an honest reflection. This task is always scheduled last."
    if day_mode == DAY_MODE_FLEX:
        description = (
            "Flex-day reflection: capture what happened, one win, and the smallest next step."
        )
    return DailyTaskItem(
        task_list=task_list,
        item_type="journal",
        title="Evening journal entry",
        description=description,
        icon="journal",
        priority="medium",
        estimated_minutes=15,
        time_slot="evening",
        suggested_time=time(hour=21, minute=0),
        why_important="Deterministic ordering rule: journal is always the final task.",
        display_order=display_order,
    )


def _journal_tone_note(tone_style: str) -> str:
    if tone_style == "supportive":
        return "Journal tone: keep today gentle and momentum-focused."
    if tone_style == "challenge":
        return "Journal tone: push slightly beyond comfort with focus."
    return ""


def build_journal_routine_adaptation(user, target_date: date, lookback_days: int = 3) -> dict:
    """
    Convert recent journal sentiment and bad-habit signals into deterministic
    next-day load and tone directives.
    """
    lookback_days = max(1, lookback_days)
    window_end = target_date - timedelta(days=1)
    window_start = target_date - timedelta(days=lookback_days)

    default_payload = {
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "entries_considered": 0,
        "average_sentiment_score": 0.0,
        "sentiment_counts": {
            "positive": 0,
            "neutral": 0,
            "negative": 0,
            "mixed": 0,
        },
        "bad_habit_signal_counts": {},
        "total_bad_habit_hits": 0,
        "tone_style": "balanced",
        "adjustments": {
            "goal_task_cap_delta": 0,
            "minutes_multiplier": 1.0,
            "deprioritize_goal_tasks": False,
            "add_split_hint": False,
        },
        "recommendations": [],
    }

    try:
        from journal.models import JournalEntry
    except Exception:
        return default_payload

    entries = list(
        JournalEntry.objects.filter(
            user=user,
            entry_date__range=(window_start, window_end),
        ).only(
            "sentiment_label",
            "sentiment_score",
            "tags",
            "reflection_raw",
            "struggle_raw",
            "tomorrow_priority_raw",
            "gratitude_raw",
        )
    )
    if not entries:
        return default_payload

    sentiment_counts = {
        "positive": 0,
        "neutral": 0,
        "negative": 0,
        "mixed": 0,
    }
    bad_habit_signal_counts: dict[str, int] = {}
    sentiment_total = 0.0

    for entry in entries:
        label = (entry.sentiment_label or "neutral").lower()
        if label not in sentiment_counts:
            label = "neutral"
        sentiment_counts[label] += 1
        sentiment_total += float(entry.sentiment_score or 0.0)

        tags_text = " ".join(str(tag) for tag in (entry.tags or []))
        merged_text = " ".join(
            [
                entry.reflection_raw or "",
                entry.struggle_raw or "",
                entry.tomorrow_priority_raw or "",
                entry.gratitude_raw or "",
                tags_text,
            ]
        ).lower()
        for signal, keywords in BAD_HABIT_SIGNAL_KEYWORDS.items():
            if any(keyword in merged_text for keyword in keywords):
                bad_habit_signal_counts[signal] = bad_habit_signal_counts.get(signal, 0) + 1

    average_sentiment_score = sentiment_total / len(entries)
    total_bad_habit_hits = sum(bad_habit_signal_counts.values())
    negative_like_count = sentiment_counts["negative"] + sentiment_counts["mixed"]

    tone_style = "balanced"
    adjustments = {
        "goal_task_cap_delta": 0,
        "minutes_multiplier": 1.0,
        "deprioritize_goal_tasks": False,
        "add_split_hint": False,
    }
    recommendations: list[str] = []

    if negative_like_count >= 2 or average_sentiment_score <= -0.2:
        tone_style = "supportive"
        adjustments.update(
            {
                "goal_task_cap_delta": -2,
                "minutes_multiplier": 0.9,
                "deprioritize_goal_tasks": True,
            }
        )
        recommendations.extend(
            [
                "Use a lighter emotional load day with easier wins first.",
                "Keep momentum with shorter focused blocks.",
            ]
        )
    elif sentiment_counts["positive"] >= 2 and average_sentiment_score >= 0.2:
        tone_style = "challenge"
        adjustments.update(
            {
                "goal_task_cap_delta": 1,
                "minutes_multiplier": 1.05,
            }
        )
        recommendations.extend(
            [
                "Leverage positive momentum with one controlled stretch task.",
            ]
        )

    if total_bad_habit_hits >= 2:
        tone_style = "supportive"
        adjustments["goal_task_cap_delta"] -= 1
        adjustments["minutes_multiplier"] *= 0.9
        adjustments["deprioritize_goal_tasks"] = True
        adjustments["add_split_hint"] = True
        recommendations.extend(
            [
                "Break tasks into very small first actions to counter bad-habit loops.",
                "Front-load high-friction work before distraction windows.",
            ]
        )

    adjustments["minutes_multiplier"] = max(0.7, min(1.2, adjustments["minutes_multiplier"]))

    return {
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "entries_considered": len(entries),
        "average_sentiment_score": round(average_sentiment_score, 3),
        "sentiment_counts": sentiment_counts,
        "bad_habit_signal_counts": bad_habit_signal_counts,
        "total_bad_habit_hits": total_bad_habit_hits,
        "tone_style": tone_style,
        "adjustments": adjustments,
        "recommendations": recommendations,
    }


def build_weekly_friction_audit(user, target_date: date, lookback_days: int = 7) -> dict:
    """
    Analyze skipped task reasons from the previous week and produce automatic
    plan-adjustment directives for the next generated day.
    """
    lookback_days = max(1, lookback_days)
    window_end = target_date - timedelta(days=1)
    window_start = target_date - timedelta(days=lookback_days)

    skipped_items = DailyTaskItem.objects.filter(
        task_list__user=user,
        task_list__date__range=(window_start, window_end),
        is_skipped=True,
        removed_by_user=False,
    ).values_list("skip_reason", flat=True)

    reason_counts = {
        "time_pressure": 0,
        "low_energy": 0,
        "difficulty": 0,
        "other": 0,
    }
    total_skips = 0
    for reason in skipped_items:
        total_skips += 1
        reason_counts[_classify_skip_reason(reason)] += 1

    dominant_reason = max(reason_counts, key=reason_counts.get) if total_skips else "none"
    adjustments = {
        "goal_task_cap_delta": 0,
        "minutes_multiplier": 1.0,
        "deprioritize_goal_tasks": False,
        "add_split_hint": False,
    }
    recommendations: list[str] = []

    if total_skips >= 2 and dominant_reason == "time_pressure":
        adjustments.update(
            {
                "goal_task_cap_delta": -3,
                "minutes_multiplier": 0.85,
            }
        )
        recommendations.extend(
            [
                "Reduce daily goal-task volume for recovery week.",
                "Shorten planned duration blocks to lower schedule friction.",
            ]
        )
    elif total_skips >= 2 and dominant_reason == "low_energy":
        adjustments.update(
            {
                "goal_task_cap_delta": -2,
                "minutes_multiplier": 0.9,
                "deprioritize_goal_tasks": True,
            }
        )
        recommendations.extend(
            [
                "Temporarily reduce cognitive intensity until streak stabilizes.",
                "Prioritize easier wins to rebuild momentum.",
            ]
        )
    elif total_skips >= 2 and dominant_reason == "difficulty":
        adjustments.update(
            {
                "goal_task_cap_delta": -2,
                "minutes_multiplier": 0.8,
                "add_split_hint": True,
            }
        )
        recommendations.extend(
            [
                "Break complex tasks into smaller first steps.",
                "Use shorter work blocks while task clarity improves.",
            ]
        )

    return {
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "total_skips": total_skips,
        "reason_counts": reason_counts,
        "dominant_reason": dominant_reason,
        "adjustments": adjustments,
        "recommendations": recommendations,
    }


def _is_sunday(target_date: date) -> bool:
    return target_date.weekday() == 6


def _scale_minutes_multiplier_from_level(level: int) -> float:
    return max(0.75, min(1.25, 1.0 + (0.05 * level)))


def _evaluate_previous_day_outcome(user, target_date: date) -> str:
    """
    Determine the adaptive outcome for yesterday:
    - success: day fully completed
    - miss: day exists and is not fully completed
    - neutral: no day found
    """
    previous_date = target_date - timedelta(days=1)
    previous_list = DailyTaskList.objects.filter(user=user, date=previous_date).first()
    if not previous_list:
        return "neutral"
    if previous_list.is_fully_completed:
        return "success"
    return "miss"


def _count_consecutive_outcomes(
    user,
    target_date: date,
    *,
    outcome: str,
    max_lookback_days: int = 30,
) -> int:
    """
    Count consecutive successful or missed days ending on yesterday.
    """
    expected_success = outcome == "success"
    consecutive = 0
    for offset in range(1, max_lookback_days + 1):
        day = target_date - timedelta(days=offset)
        day_list = DailyTaskList.objects.filter(user=user, date=day).first()
        if not day_list:
            break
        is_success = bool(day_list.is_fully_completed)
        if is_success != expected_success:
            break
        consecutive += 1
    return consecutive


def _apply_weekly_reset_if_needed(state: AdaptiveRoadmapState, target_date: date) -> None:
    """
    Reset weekly miss counters when the ISO week changes.
    """
    if state.weekly_reset_anchor is None:
        state.weekly_reset_anchor = target_date
        return
    if state.weekly_reset_anchor.isocalendar()[:2] != target_date.isocalendar()[:2]:
        state.weekly_miss_days = 0
        state.weekly_reset_anchor = target_date


def build_adaptive_roadmap_adjustment(user, target_date: date) -> dict:
    """
    Adaptive roadmap trigger engine (TASK-B003 contract):
    - Automatic evaluation runs as part of daily generation.
    - 5-day miss recovery trigger reduces load aggressively.
    - Sunday sprint rebuild trigger applies once per Sunday.
    - Progressive/reversible scaling adjusts level with cooldown.
    """
    state, _ = AdaptiveRoadmapState.objects.get_or_create(user=user)
    _apply_weekly_reset_if_needed(state, target_date)

    state.consecutive_success_days = _count_consecutive_outcomes(
        user=user,
        target_date=target_date,
        outcome="success",
    )
    state.consecutive_miss_days = _count_consecutive_outcomes(
        user=user,
        target_date=target_date,
        outcome="miss",
    )
    state.weekly_miss_days = DailyTaskList.objects.filter(
        user=user,
        date__gte=target_date - timedelta(days=6),
        date__lt=target_date,
        is_fully_completed=False,
    ).count()
    state.last_evaluated_date = target_date

    can_change_scale = (
        state.last_scale_change_date is None
        or (target_date - state.last_scale_change_date).days >= ADAPTIVE_SCALE_COOLDOWN_DAYS
    )
    if can_change_scale:
        if (
            state.consecutive_success_days >= 3
            and state.current_scale_level < ADAPTIVE_SCALE_MAX
        ):
            state.current_scale_level += 1
            state.last_scale_change_date = target_date
        elif (
            state.consecutive_miss_days >= 3
            and state.current_scale_level > ADAPTIVE_SCALE_MIN
        ):
            state.current_scale_level -= 1
            state.last_scale_change_date = target_date

    adjustments = {
        "goal_task_cap_delta": state.current_scale_level,
        "minutes_multiplier": _scale_minutes_multiplier_from_level(state.current_scale_level),
        "deprioritize_goal_tasks": state.current_scale_level < 0,
        "add_split_hint": state.current_scale_level < 0,
    }
    recommendations: list[str] = []
    triggers = {
        "miss_recovery_triggered": False,
        "sunday_rebuild_triggered": False,
    }

    if state.consecutive_miss_days >= 5:
        triggers["miss_recovery_triggered"] = True
        adjustments["goal_task_cap_delta"] -= 4
        adjustments["minutes_multiplier"] *= 0.75
        adjustments["deprioritize_goal_tasks"] = True
        adjustments["add_split_hint"] = True
        recommendations.extend(
            [
                "Recovery mode: reduce plan load after 5 consecutive miss days.",
                "Prioritize minimum viable wins before intensity is restored.",
            ]
        )

    if _is_sunday(target_date) and state.last_sunday_rebuild_date != target_date:
        triggers["sunday_rebuild_triggered"] = True
        state.last_sunday_rebuild_date = target_date
        adjustments["goal_task_cap_delta"] -= 2
        adjustments["minutes_multiplier"] *= 0.9
        adjustments["add_split_hint"] = True
        recommendations.append(
            "Sunday sprint rebuild: generate a lighter restart day with first-step bias."
        )

    adjustments["minutes_multiplier"] = max(
        0.7, min(1.25, float(adjustments["minutes_multiplier"]))
    )
    state.save()

    return {
        "target_date": target_date.isoformat(),
        "state": {
            "current_scale_level": state.current_scale_level,
            "consecutive_miss_days": state.consecutive_miss_days,
            "consecutive_success_days": state.consecutive_success_days,
            "weekly_miss_days": state.weekly_miss_days,
        },
        "triggers": triggers,
        "adjustments": adjustments,
        "recommendations": recommendations,
    }


def _build_adaptive_response_metadata(adaptive_adjustment: dict) -> dict:
    return {
        "target_date": adaptive_adjustment.get("target_date"),
        "state": adaptive_adjustment.get("state", {}),
        "triggers": adaptive_adjustment.get("triggers", {}),
        "adjustments": adaptive_adjustment.get("adjustments", {}),
        "recommendations": adaptive_adjustment.get("recommendations", []),
        "policy": {
            "scale_level_min": ADAPTIVE_SCALE_MIN,
            "scale_level_max": ADAPTIVE_SCALE_MAX,
            "scale_change_cooldown_days": ADAPTIVE_SCALE_COOLDOWN_DAYS,
            "miss_recovery_threshold_days": 5,
            "sunday_rebuild_rule": "once_per_sunday",
        },
    }


def get_or_create_today_task_list(
    user,
    target_date: date,
    force_regenerate: bool = False,
    day_mode: str | None = None,
    day_mode_note: str = "",
) -> tuple[DailyTaskList, bool]:
    """
    Return (task_list, created).

    If a DailyTaskList already exists for this user+date, return it.
    Otherwise, build one from the goal hierarchy + active habits, then
    call the AI only for motivation/mantra text.

    force_regenerate rebuilds an existing day when explicitly requested.
    This is used to refresh routine composition after scheduling-rule updates.
    """
    existing = DailyTaskList.objects.filter(user=user, date=target_date).first()
    if existing:
        if force_regenerate:
            existing.delete()
        else:
            return existing, False

    mode_context = _resolve_and_persist_day_mode(
        user=user,
        target_date=target_date,
        explicit_day_mode=day_mode,
        day_mode_note=day_mode_note,
    )
    resolved_day_mode = mode_context["day_mode"]
    wake_baseline = get_wake_baseline_metadata(user=user)
    wake_baseline_minutes = wake_baseline.get("baseline_minutes")
    wake_has_baseline = bool(wake_baseline.get("is_available"))
    wake_default_slot = wake_baseline.get("default_slot") or "afternoon"

    friction_audit = build_weekly_friction_audit(user=user, target_date=target_date)
    journal_adaptation = build_journal_routine_adaptation(user=user, target_date=target_date)
    adaptive_adjustment = build_adaptive_roadmap_adjustment(user=user, target_date=target_date)
    journal_adjustments = journal_adaptation["adjustments"]
    adaptive_adjustments = adaptive_adjustment["adjustments"]
    tone_style = journal_adaptation["tone_style"]
    tone_note = _journal_tone_note(tone_style)

    goal_task_limit = max(
        MIN_DAILY_GOAL_TASKS,
        MAX_DAILY_GOAL_TASKS
        + int(friction_audit["adjustments"]["goal_task_cap_delta"])
        + int(journal_adjustments["goal_task_cap_delta"])
        + int(adaptive_adjustments["goal_task_cap_delta"]),
    )
    minutes_multiplier = (
        float(friction_audit["adjustments"]["minutes_multiplier"])
        * float(journal_adjustments["minutes_multiplier"])
        * float(adaptive_adjustments["minutes_multiplier"])
    )
    minutes_multiplier = max(0.7, min(1.25, minutes_multiplier))
    deprioritize_goal_tasks = bool(
        friction_audit["adjustments"]["deprioritize_goal_tasks"]
        or journal_adjustments["deprioritize_goal_tasks"]
        or adaptive_adjustments["deprioritize_goal_tasks"]
    )
    add_split_hint = bool(
        friction_audit["adjustments"]["add_split_hint"]
        or journal_adjustments["add_split_hint"]
        or adaptive_adjustments["add_split_hint"]
    )
    if resolved_day_mode == DAY_MODE_FLEX:
        deprioritize_goal_tasks = True
        add_split_hint = True

    # 1) Fetch pending goal tasks with balanced cross-goal coverage
    goal_tasks = _select_balanced_goal_tasks(user=user, limit=goal_task_limit)

    # 2) Fetch habits that should run on target_date
    habits = [
        h for h in HabitTracker.objects.filter(user=user, is_active=True)
        if h.should_include_on_date(target_date)
    ]

    event_occurrences = _get_event_occurrences_for_day(user=user, target_date=target_date)
    schedule_constraints = _fetch_day_event_constraints(
        user=user,
        target_date=target_date,
        event_occurrences=event_occurrences,
    )
    availability_by_slot = _build_available_minutes_by_slot(
        target_date=target_date,
        schedule_constraints=schedule_constraints,
    )
    total_available_minutes = sum(availability_by_slot.values())
    required_minutes_before_fallback = _calculate_required_minutes(
        habits=habits,
        goal_tasks=goal_tasks,
        minutes_multiplier=minutes_multiplier,
    )
    habits, goal_tasks, minutes_multiplier, fallback_strategy, required_minutes_after_fallback = _apply_overbooked_fallback(
        habits=habits,
        goal_tasks=goal_tasks,
        minutes_multiplier=minutes_multiplier,
        available_minutes=total_available_minutes,
    )
    if resolved_day_mode == DAY_MODE_FLEX:
        habits, goal_tasks, minutes_multiplier = _apply_flex_day_profile(
            habits=habits,
            goal_tasks=goal_tasks,
            minutes_multiplier=minutes_multiplier,
        )
        required_minutes_after_fallback = _calculate_required_minutes(
            habits=habits,
            goal_tasks=goal_tasks,
            minutes_multiplier=minutes_multiplier,
        )
        fallback_strategy = "flex_profile"

    # 3) Ask AI for motivation + mantra only
    motivation = ""
    mantra = ""
    try:
        from ai.services.DailyRoutineGenerator import DailyRoutineGenerator

        user_context = _get_user_context(user)
        user_context["routine_tone_style"] = tone_style
        user_context["event_constraints"] = {
            "available_minutes": total_available_minutes,
            "required_minutes": required_minutes_before_fallback,
            "fallback_strategy": fallback_strategy,
            "occupied_window_count": len(schedule_constraints.get("occupied_windows", [])),
        }
        user_context["journal_load_signal"] = {
            "average_sentiment_score": journal_adaptation["average_sentiment_score"],
            "total_bad_habit_hits": journal_adaptation["total_bad_habit_hits"],
            "entries_considered": journal_adaptation["entries_considered"],
        }
        generator = DailyRoutineGenerator()
        ai_result = generator.generate_motivation_and_mantra(
            user_context=user_context,
            goal_tasks=list(goal_tasks),
            habits=habits,
            events=event_occurrences,
            target_date=target_date,
        )
        if ai_result.get("status") == "success":
            data = ai_result.get("data", {})
            motivation = data.get("motivation", "")
            mantra = data.get("mantra", "")
    except Exception:
        logger.exception(
            "Could not generate motivation for user %s - continuing without it",
            user.id,
        )
    if not motivation:
        if tone_style == "supportive":
            motivation = "Small consistent wins count today. Keep the plan gentle and finish the first step."
        elif tone_style == "challenge":
            motivation = "Momentum is on your side. Focus deep and execute one stretch task with intent."
        else:
            motivation = "Stay consistent today and complete the next meaningful actions."
    if not mantra:
        if tone_style == "supportive":
            mantra = "Gentle pace, strong consistency."
        elif tone_style == "challenge":
            mantra = "Focused effort compounds fast."
        else:
            mantra = "One clear task at a time."

    # 4) Build list + items, race-safe against concurrent calls
    try:
        with transaction.atomic():
            serialized_occupied_windows = []
            for item in schedule_constraints.get("occupied_windows", []):
                serialized_occupied_windows.append(
                    {
                        "source": item.get("source", "event"),
                        "event_id": item.get("event_id", ""),
                        "occurrence_id": item.get("occurrence_id", ""),
                        "title": item.get("title", ""),
                        "start_at": item["start_at"].isoformat(),
                        "end_at": item["end_at"].isoformat(),
                        "constraint_mode": item.get("constraint_mode", "hard"),
                        "routine_policy": item.get("routine_policy", "block"),
                    }
                )

            fit_status = "fit"
            if fallback_strategy in ("compress", "defer"):
                fit_status = "partial_fit"
            elif fallback_strategy == "partial":
                fit_status = "partial_fit"

            task_list = DailyTaskList.objects.create(
                user=user,
                date=target_date,
                daily_motivation=motivation,
                daily_mantra=mantra,
                schedule_constraints={
                    "timezone": schedule_constraints.get("timezone", "UTC"),
                    "window_start": schedule_constraints.get("window_start"),
                    "window_end": schedule_constraints.get("window_end"),
                    "occupied_windows": serialized_occupied_windows,
                    "fit_summary": {
                        "available_minutes": total_available_minutes,
                        "required_minutes": required_minutes_after_fallback,
                        "fit_status": fit_status,
                        "fallback_strategy": fallback_strategy,
                    },
                    "day_mode": {
                        "value": resolved_day_mode,
                        "source": mode_context["source"],
                        "carried_from_date": mode_context["carried_from_date"],
                        "note": mode_context["day_mode_note"],
                    },
                    "adaptive_roadmap": _build_adaptive_response_metadata(adaptive_adjustment),
                    "wake_baseline": wake_baseline,
                },
            )

            items_to_create = []
            order = 0

            # Events first
            for occurrence in event_occurrences:
                start_dt = occurrence.get("start_at")
                end_dt = occurrence.get("end_at")
                event_slot = _infer_time_slot_from_interval(
                    start_dt,
                    end_dt,
                    target_date=target_date,
                    fallback="afternoon",
                )
                start_label = start_dt.strftime("%H:%M") if start_dt else ""
                end_label = end_dt.strftime("%H:%M") if end_dt else ""
                event_description = f"Scheduled event window: {start_label} - {end_label}"
                if occurrence.get("routine_policy"):
                    event_description = (
                        f"{event_description}. Routine policy: {occurrence['routine_policy']}."
                    )
                items_to_create.append(
                    DailyTaskItem(
                        task_list=task_list,
                        item_type="event",
                        event=occurrence.get("event"),
                        title=occurrence.get("title", "Scheduled Event"),
                        description=event_description,
                        icon="calendar",
                        priority="high"
                        if occurrence.get("constraint_mode", "hard") == "hard"
                        else "medium",
                        estimated_minutes=max(10, int(occurrence.get("duration_minutes", 0) or 0)),
                        time_slot=event_slot,
                        suggested_time=start_dt.time() if start_dt else _default_time_for_slot(event_slot),
                        why_important="Scheduled event commitment.",
                        display_order=order,
                    )
                )
                order += 1

            # Habits next
            for habit in habits:
                habit_description = (habit.description or "").strip() or (habit.reason_body or "").strip()
                habit_why_important = (habit.why_important or "").strip() or (habit.reason_headline or "").strip()
                habit_minutes = _scale_minutes(habit.estimated_minutes, minutes_multiplier)
                if habit.suggested_time:
                    habit_slot = _infer_time_slot_from_datetime(
                        datetime.combine(target_date, habit.suggested_time),
                        fallback=wake_default_slot if wake_has_baseline else "morning",
                    )
                    habit_uses_fallback = False
                else:
                    habit_slot = _infer_time_slot_from_text(
                        habit.name,
                        habit_description,
                        fallback=wake_default_slot if wake_has_baseline else "morning",
                    )
                    habit_uses_fallback = True
                habit_slot = _select_available_slot(
                    preferred_slot=habit_slot,
                    availability_by_slot=availability_by_slot,
                    required_minutes=habit_minutes,
                )
                _reserve_slot_minutes(
                    availability_by_slot=availability_by_slot,
                    slot_name=habit_slot,
                    minutes=habit_minutes,
                )
                items_to_create.append(
                    DailyTaskItem(
                        task_list=task_list,
                        item_type="habit",
                        habit=habit,
                        related_goal=habit.linked_goal,
                        title=habit.name,
                        description=habit_description,
                        icon=habit.icon,
                        priority=habit.priority,
                        estimated_minutes=habit_minutes,
                        time_slot=habit_slot,
                        suggested_time=(
                            habit.suggested_time
                            if habit.suggested_time
                            else _default_time_for_slot(
                                habit_slot,
                                wake_baseline_minutes=wake_baseline_minutes,
                                use_wake_baseline=habit_uses_fallback,
                            )
                        ),
                        why_important=_append_adjustment_note(habit_why_important, tone_note),
                        display_order=order,
                    )
                )
                order += 1

            # Goal tasks next
            for task in goal_tasks:
                goal = task.subgoal.milestone.goal
                task_minutes = _scale_minutes(task.estimated_duration_minutes, minutes_multiplier)
                if task.preferred_time_slot:
                    task_slot = task.preferred_time_slot
                    task_uses_fallback = False
                else:
                    task_slot = _infer_time_slot_from_text(
                        task.title,
                        task.description,
                        fallback=wake_default_slot if wake_has_baseline else "afternoon",
                    )
                    task_uses_fallback = True
                task_slot = _select_available_slot(
                    preferred_slot=task_slot,
                    availability_by_slot=availability_by_slot,
                    required_minutes=task_minutes,
                )
                _reserve_slot_minutes(
                    availability_by_slot=availability_by_slot,
                    slot_name=task_slot,
                    minutes=task_minutes,
                )
                adjusted_priority = (
                    _shift_priority_down(task.priority) if deprioritize_goal_tasks else task.priority
                )
                adjusted_description = task.description or ""
                if add_split_hint:
                    adjusted_description = _append_adjustment_note(
                        adjusted_description,
                        "Friction adjustment: start with a 15-minute first step.",
                    )
                if tone_note:
                    adjusted_description = _append_adjustment_note(adjusted_description, tone_note)
                items_to_create.append(
                    DailyTaskItem(
                        task_list=task_list,
                        item_type="goal_task",
                        goal_task=task,
                        related_goal=goal,
                        title=task.title,
                        description=adjusted_description,
                        icon="target",
                        priority=adjusted_priority,
                        estimated_minutes=task_minutes,
                        time_slot=task_slot,
                        suggested_time=task.scheduled_time
                        or _default_time_for_slot(
                            task_slot,
                            wake_baseline_minutes=wake_baseline_minutes,
                            use_wake_baseline=task_uses_fallback,
                        ),
                        why_important=f"Part of: {goal.title}",
                        display_order=order,
                    )
                )
                order += 1

            # Deterministic ordering rule: journal is always the final task.
            items_to_create.append(
                _build_journal_last_task(
                    task_list=task_list,
                    display_order=order,
                    day_mode=resolved_day_mode,
                )
            )

            DailyTaskItem.objects.bulk_create(items_to_create)
            task_list.update_progress()
    except IntegrityError:
        # Concurrent requests can race between read and create.
        # If the row was created by another request, return it.
        existing = DailyTaskList.objects.filter(user=user, date=target_date).first()
        if existing:
            return existing, False
        raise

    logger.info(
        "DailyTaskList created for user %s on %s - %d events, %d habits, %d goal tasks",
        user.id,
        target_date,
        len(event_occurrences),
        len(habits),
        len(goal_tasks),
    )
    return task_list, True


def update_discipline_streak(user, task_list: DailyTaskList):
    """
    Called after every task completion. Updates DisciplineStreak only when
    the full day is done so the streak counter reflects whole-day discipline.
    """
    if not task_list.is_fully_completed:
        return

    streak, _ = DisciplineStreak.objects.get_or_create(user=user)
    streak.update_streak(date=task_list.date, all_tasks_completed=True)


def _get_user_context(user) -> dict:
    """Fetch user situation context for AI personalization."""
    try:
        from authentication.models import UserPersonalDetails
        from goal.models import UserCurrentSituationGoal

        personal = UserPersonalDetails.objects.get(user=user)
        situation = UserCurrentSituationGoal.objects.get(user_personal_details=personal)
        return {
            "current_role": situation.current_role,
            "key_skills": situation.key_skills,
            "main_goals": situation.main_goals,
            "constraints": situation.constraints,
            "priority_areas": situation.priority_areas,
        }
    except UserPersonalDetails.DoesNotExist:
        logger.warning("No UserPersonalDetails for user %s", user.id)
        return {}
    except Exception:
        logger.exception("Unexpected error fetching user context for user %s", user.id)
        return {}
