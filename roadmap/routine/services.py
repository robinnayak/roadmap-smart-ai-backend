# ==============================================================================
# roadmap/routine/services.py
# ==============================================================================
"""
Routine selection logic — pure database queries, no AI needed for task picking.
AI is only used to generate the daily motivation + mantra (two short strings).
"""
import logging
from datetime import date, time

from django.db import transaction

from goal.models import Task, Goal
from routine.models import DailyTaskList, DailyTaskItem, HabitTracker, DisciplineStreak

logger = logging.getLogger(__name__)


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


def get_or_create_today_task_list(user, target_date: date) -> tuple[DailyTaskList, bool]:
    """
    Return (task_list, created).

    If a DailyTaskList already exists for this user+date, return it.
    Otherwise, build one from the goal hierarchy + active habits, then
    call the AI only for motivation/mantra text.

    This is the single source of truth — both GenerateDailyTaskListAPIView
    and TodayTaskListAPIView call this function instead of one view calling
    the other.
    """
    existing = DailyTaskList.objects.filter(user=user, date=target_date).first()
    if existing:
        return existing, False

    # --- 1. Fetch pending goal tasks with a single optimised query -----------
    # select_related traverses the full hierarchy in one JOIN so we don't
    # hit the DB again when accessing task.subgoal.milestone.goal later.
    goal_tasks = (
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
            "subgoal__milestone__goal__priority",   # goal priority first
            "subgoal__milestone__display_order",
            "subgoal__display_order",
            "display_order",
        )[:15]  # sensible daily cap — don't overwhelm the user
    )

    # --- 2. Fetch habits that should run today --------------------------------
    habits = [
        h for h in HabitTracker.objects.filter(user=user, is_active=True)
        if h.should_include_today()
    ]

    # --- 3. Ask AI for motivation + mantra only ------------------------------
    motivation = ""
    mantra = ""
    try:
        from ai.services.DailyRoutineGenerator import DailyRoutineGenerator
        from authentication.models import UserPersonalDetails
        from goal.models import UserCurrentSituationGoal

        user_context = _get_user_context(user)
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
            mantra     = data.get("mantra", "")
    except Exception:
        logger.exception("Could not generate motivation for user %s — continuing without it", user.id)

    # --- 4. Build DailyTaskList + DailyTaskItems in one transaction ----------
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
                    estimated_minutes=habit.estimated_minutes,
                    time_slot=habit_slot,
                    suggested_time=_default_time_for_slot(habit_slot),
                    why_important=habit.why_important,
                    display_order=order,
                )
            )
            order += 1

        # Goal tasks next
        for task in goal_tasks:
            goal = task.subgoal.milestone.goal  # already in memory via select_related
            task_slot = task.preferred_time_slot or _infer_time_slot_from_text(
                task.title,
                task.description,
                fallback="afternoon",
            )
            items_to_create.append(
                DailyTaskItem(
                    task_list=task_list,
                    item_type="goal_task",
                    goal_task=task,
                    related_goal=goal,
                    title=task.title,
                    description=task.description,
                    icon="🎯",
                    priority=task.priority,
                    estimated_minutes=task.estimated_duration_minutes,
                    time_slot=task_slot,
                    suggested_time=task.scheduled_time or _default_time_for_slot(task_slot),
                    why_important=f"Part of: {goal.title}",
                    display_order=order,
                )
            )
            order += 1

        DailyTaskItem.objects.bulk_create(items_to_create)
        task_list.update_progress()

    logger.info(
        "DailyTaskList created for user %s on %s — %d habits, %d goal tasks",
        user.id, target_date, len(habits), len(list(goal_tasks)),
    )
    return task_list, True


def update_discipline_streak(user, task_list: DailyTaskList):
    """
    Called after every task completion. Updates DisciplineStreak only when
    the full day is done so the streak counter reflects whole-day discipline.

    FIX: DailyTaskList.update_progress() was setting is_fully_completed=True
         but never telling DisciplineStreak about it. Streak always read 0.
    """
    if not task_list.is_fully_completed:
        return  # Day not done yet — nothing to update

    streak, _ = DisciplineStreak.objects.get_or_create(user=user)
    streak.update_streak(date=task_list.date, all_tasks_completed=True)


def _get_user_context(user) -> dict:
    """Fetch user situation context for AI personalisation."""
    try:
        from authentication.models import UserPersonalDetails
        from goal.models import UserCurrentSituationGoal

        personal  = UserPersonalDetails.objects.get(user=user)
        situation = UserCurrentSituationGoal.objects.get(user_personal_details=personal)
        return {
            "current_role":    situation.current_role,
            "key_skills":      situation.key_skills,
            "main_goals":      situation.main_goals,
            "constraints":     situation.constraints,
            "priority_areas":  situation.priority_areas,
        }
    except UserPersonalDetails.DoesNotExist:
        logger.warning("No UserPersonalDetails for user %s", user.id)
        return {}
    except Exception:
        logger.exception("Unexpected error fetching user context for user %s", user.id)
        return {}
