# ==============================================================================
# roadmap/ai/services/daily_routine_generator.py
# ==============================================================================
"""
Deterministic daily motivation and mantra generation.

Task selection remains in routine/services.py. This module only turns the
already-selected routine inputs into short, predictable text.
"""
from __future__ import annotations

from collections import Counter
from datetime import date


class DailyRoutineGenerator:
    CATEGORY_FAMILIES = {
        "career": {
            "focus": "career traction",
            "action": "ship useful progress",
        },
        "business": {
            "focus": "business traction",
            "action": "move revenue work forward",
        },
        "financial": {
            "focus": "financial discipline",
            "action": "make the next money move cleanly",
        },
        "finance": {
            "focus": "financial discipline",
            "action": "make the next money move cleanly",
        },
        "health": {
            "focus": "physical consistency",
            "action": "protect energy and follow through",
        },
        "fitness": {
            "focus": "physical consistency",
            "action": "protect energy and follow through",
        },
        "personal": {
            "focus": "personal momentum",
            "action": "follow through on what matters",
        },
        "relationships": {
            "focus": "relationship consistency",
            "action": "show up with intention",
        },
        "productivity": {
            "focus": "steady progress",
            "action": "finish the next meaningful action",
        },
    }

    def generate_motivation_and_mantra(
        self,
        user_context: dict,
        goal_tasks: list,
        habits: list,
        events: list | None,
        target_date: date,
        user=None,
    ) -> dict:
        signals = self._build_signals(
            user_context=user_context or {},
            goal_tasks=goal_tasks or [],
            habits=habits or [],
            events=events or [],
            target_date=target_date,
        )
        return {
            "status": "success",
            "data": {
                "motivation": self._build_motivation(signals),
                "mantra": self._build_mantra(signals),
            },
        }

    def _build_signals(
        self,
        *,
        user_context: dict,
        goal_tasks: list,
        habits: list,
        events: list,
        target_date: date,
    ) -> dict:
        streak_days = int(user_context.get("streak_days", 0) or 0)
        scale_level = int(user_context.get("current_scale_level", 0) or 0)
        dominant_category = self._dominant_category(goal_tasks)
        category_family = self.CATEGORY_FAMILIES.get(
            dominant_category,
            self.CATEGORY_FAMILIES["productivity"],
        )
        urgency = self._urgency_bucket(goal_tasks, target_date)
        load_shape = self._load_bucket(goal_tasks, habits, events)
        return {
            "streak_bucket": self._streak_bucket(streak_days),
            "streak_days": streak_days,
            "scale_bucket": self._scale_bucket(scale_level),
            "scale_level": scale_level,
            "urgency_bucket": urgency,
            "load_bucket": load_shape,
            "dominant_category": dominant_category,
            "category_family": category_family,
            "goal_task_count": len(goal_tasks),
            "habit_count": len(habits),
            "event_count": len(events),
        }

    @staticmethod
    def _streak_bucket(streak_days: int) -> str:
        if streak_days >= 7:
            return "strong"
        if streak_days >= 2:
            return "building"
        return "cold"

    @staticmethod
    def _scale_bucket(scale_level: int) -> str:
        if scale_level <= -1:
            return "recovery"
        if scale_level >= 1:
            return "stretch"
        return "neutral"

    @staticmethod
    def _dominant_category(goal_tasks: list) -> str:
        counts: Counter[str] = Counter()
        for task in goal_tasks:
            try:
                category = (task.subgoal.milestone.goal.primary_category or "").strip().lower()
            except AttributeError:
                category = ""
            if category:
                counts[category] += 1

        if not counts:
            return "productivity"
        return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]

    @staticmethod
    def _urgency_bucket(goal_tasks: list, target_date: date) -> str:
        goal_deadlines: list[int] = []
        for task in goal_tasks:
            try:
                goal_target = task.subgoal.milestone.goal.target_date
            except AttributeError:
                goal_target = None
            if goal_target:
                goal_deadlines.append((goal_target - target_date).days)

        if not goal_deadlines:
            return "no_target"

        nearest_deadline = min(goal_deadlines)
        if nearest_deadline < 0:
            return "overdue"
        if nearest_deadline <= 7:
            return "near_deadline"
        return "normal_horizon"

    @staticmethod
    def _load_bucket(goal_tasks: list, habits: list, events: list) -> str:
        high_priority_items = 0
        total_minutes = 0

        for task in goal_tasks:
            if getattr(task, "priority", "") == "high":
                high_priority_items += 1
            total_minutes += int(getattr(task, "estimated_duration_minutes", 0) or 0)

        for habit in habits:
            if getattr(habit, "priority", "") == "high":
                high_priority_items += 1
            total_minutes += int(getattr(habit, "estimated_minutes", 0) or 0)

        for event in events:
            if event.get("constraint_mode", "hard") == "hard":
                high_priority_items += 1
            total_minutes += int(event.get("duration_minutes", 0) or 0)

        actionable_count = len(goal_tasks) + len(habits)
        if high_priority_items >= 3 or total_minutes >= 240:
            return "high_priority_heavy"
        if actionable_count <= 2 and total_minutes <= 90:
            return "low_pressure"
        return "balanced"

    def _build_motivation(self, signals: dict) -> str:
        focus = signals["category_family"]["focus"]
        action = signals["category_family"]["action"]

        opening = {
            ("cold", "recovery"): "Today is a reset day, so keep the bar clear and kind.",
            ("cold", "neutral"): "Today is a fresh start, so begin with one clean win.",
            ("cold", "stretch"): "Start clean, then lean into one meaningful stretch step.",
            ("building", "recovery"): "You already have momentum, so protect it with a manageable plan.",
            ("building", "neutral"): "Momentum is building, so stay steady and keep the next action obvious.",
            ("building", "stretch"): "Momentum is building, so use it to push one stretch level higher with control.",
            ("strong", "recovery"): "Your streak is strong, and protecting consistency matters more than forcing volume.",
            ("strong", "neutral"): "Your streak is strong, so keep the standard high and the execution calm.",
            ("strong", "stretch"): "Your streak is strong, so this is a good day to press into a stretch task.",
        }[(signals["streak_bucket"], signals["scale_bucket"])]

        urgency_clause = {
            "overdue": "There is overdue work in play, so close one important loop before anything else.",
            "near_deadline": "A deadline is close, so put the most time-sensitive work first.",
            "normal_horizon": f"Keep today's attention on {focus} and {action}.",
            "no_target": f"Use today to build {focus} through deliberate follow-through.",
        }[signals["urgency_bucket"]]

        load_clause = {
            "high_priority_heavy": "The load is heavy, so protect focus and finish the highest-value task before expanding scope.",
            "balanced": "The load is balanced, so move deliberately and stack solid completions.",
            "low_pressure": "The load is lighter, so finish cleanly and leave yourself with usable energy.",
        }[signals["load_bucket"]]

        return f"{opening} {urgency_clause} {load_clause}"

    def _build_mantra(self, signals: dict) -> str:
        starter = {
            "cold": "Start simple",
            "building": "Stay consistent",
            "strong": "Protect the streak",
        }[signals["streak_bucket"]]

        middle = {
            "recovery": "pace it cleanly",
            "neutral": "keep the standard",
            "stretch": "push the stretch task",
        }[signals["scale_bucket"]]

        finish = {
            "overdue": "clear the overdue priority",
            "near_deadline": "honor the deadline",
            "normal_horizon": signals["category_family"]["action"],
            "no_target": "finish the next meaningful action",
        }[signals["urgency_bucket"]]

        return f"{starter}, {middle}, {finish}."
