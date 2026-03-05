# ==============================================================================
# roadmap/routine/services.py
# ==============================================================================
"""
Routine selection logic - pure database queries, no AI needed for task picking.
AI is only used to generate the daily motivation + mantra (two short strings).
"""
import logging
from collections import deque
from datetime import date, time, timedelta

from django.db import transaction
from django.db.utils import IntegrityError

from goal.models import Task
from routine.models import (
    AdaptiveRoadmapState,
    DailyTaskList,
    DailyTaskItem,
    DisciplineStreak,
    HabitTracker,
)

logger = logging.getLogger(__name__)

MAX_DAILY_GOAL_TASKS = 15
GOAL_PRIORITY_ORDER = {"high": 3, "medium": 2, "low": 1}
MIN_DAILY_GOAL_TASKS = 5
ADAPTIVE_SCALE_MIN = -3
ADAPTIVE_SCALE_MAX = 3
ADAPTIVE_SCALE_COOLDOWN_DAYS = 2

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


def _default_time_for_slot(slot: str | None):
    mapping = {
        "morning": time(hour=8, minute=0),
        "afternoon": time(hour=14, minute=0),
        "evening": time(hour=19, minute=0),
    }
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


def get_or_create_today_task_list(
    user, target_date: date, force_regenerate: bool = False
) -> tuple[DailyTaskList, bool]:
    """
    Return (task_list, created).

    If a DailyTaskList already exists for this user+date, return it.
    Otherwise, build one from the goal hierarchy + active habits, then
    call the AI only for motivation/mantra text.

    force_regenerate only rebuilds an existing day if it is currently empty
    (0 total_tasks, 0 completed_tasks). This avoids destructive resets.
    """
    existing = DailyTaskList.objects.filter(user=user, date=target_date).first()
    if existing:
        if (
            force_regenerate
            and existing.total_tasks == 0
            and existing.completed_tasks == 0
        ):
            existing.delete()
        else:
            return existing, False

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

    # 1) Fetch pending goal tasks with balanced cross-goal coverage
    goal_tasks = _select_balanced_goal_tasks(user=user, limit=goal_task_limit)

    # 2) Fetch habits that should run on target_date
    habits = [
        h for h in HabitTracker.objects.filter(user=user, is_active=True)
        if h.should_include_on_date(target_date)
    ]

    # 3) Ask AI for motivation + mantra only
    motivation = ""
    mantra = ""
    try:
        from ai.services.DailyRoutineGenerator import DailyRoutineGenerator

        user_context = _get_user_context(user)
        user_context["routine_tone_style"] = tone_style
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
            task_list = DailyTaskList.objects.create(
                user=user,
                date=target_date,
                daily_motivation=motivation,
                daily_mantra=mantra,
            )

            items_to_create = []
            order = 0

            # Habits first
            for habit in habits:
                habit_slot = _infer_time_slot_from_text(
                    habit.name,
                    habit.description,
                    fallback="morning",
                )
                items_to_create.append(
                    DailyTaskItem(
                        task_list=task_list,
                        item_type="habit",
                        habit=habit,
                        related_goal=habit.linked_goal,
                        title=habit.name,
                        description=habit.description,
                        icon=habit.icon,
                        priority=habit.priority,
                        estimated_minutes=_scale_minutes(habit.estimated_minutes, minutes_multiplier),
                        time_slot=habit_slot,
                        suggested_time=_default_time_for_slot(habit_slot),
                        why_important=_append_adjustment_note(habit.why_important, tone_note),
                        display_order=order,
                    )
                )
                order += 1

            # Goal tasks next
            for task in goal_tasks:
                goal = task.subgoal.milestone.goal
                task_slot = task.preferred_time_slot or _infer_time_slot_from_text(
                    task.title,
                    task.description,
                    fallback="afternoon",
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
                        estimated_minutes=_scale_minutes(task.estimated_duration_minutes, minutes_multiplier),
                        time_slot=task_slot,
                        suggested_time=task.scheduled_time
                        or _default_time_for_slot(task_slot),
                        why_important=f"Part of: {goal.title}",
                        display_order=order,
                    )
                )
                order += 1

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
        "DailyTaskList created for user %s on %s - %d habits, %d goal tasks",
        user.id,
        target_date,
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
