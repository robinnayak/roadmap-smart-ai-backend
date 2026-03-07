from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import UUID


class DataCollector:
    MIN_IN_PROGRESS_DAYS = 7
    MIN_COMPLETE_DAYS_WITHOUT_GOAL_COMPLETION = 180

    def __init__(
        self,
        user,
        goal_id: str | UUID | None = None,
        goal_ids: list[str | UUID] | None = None,
        include_all_goals: bool = False,
        selected_goals: list | None = None,
        selection_mode: str | None = None,
        privacy_settings: dict | None = None,
    ):
        self.user = user
        self.privacy_settings = privacy_settings or {}
        self._selected_goals = list(selected_goals or [])
        self.include_all_goals = include_all_goals
        self.selection_mode = selection_mode

        if not self._selected_goals:
            resolved = self._resolve_selected_goals(
                goal_id=goal_id,
                goal_ids=goal_ids,
                include_all_goals=include_all_goals,
            )
            self._selected_goals = resolved["selected_goals"]
            self.selection_mode = self.selection_mode or resolved["selection_mode"]

        self.selection_mode = self.selection_mode or self._infer_selection_mode(self._selected_goals)

    def collect_all_data(self) -> dict[str, Any]:
        goals = self._get_goals()
        journals = self._get_journals()
        streaks = self._get_streaks(journals=journals)

        return {
            "user": self.user,
            "profile": self._get_profile(),
            "goal": self._build_goal_summary(goals),
            "goals": goals,
            "journals": journals,
            "streaks": streaks,
            "word_frequencies": self._get_word_frequencies(),
            "derived_milestones": self._get_existing_derived_milestones(),
            "selection_mode": self.selection_mode,
        }

    def check_eligibility(self, goal_id: str | UUID | None = None) -> dict[str, Any]:
        goals = self._get_goals()
        journals = self._get_journals()
        journal_days, goal_age_days = self._calculate_data_day_breakdown(goals=goals, journals=journals)
        days_of_data = len(self._combined_date_coverage(goals=goals, journals=journals))

        qualifying_goal = self._find_complete_unlock_goal(goals)
        goal_is_completed = bool(qualifying_goal and (qualifying_goal.get("status") or "").lower() == "completed")
        goal_is_due = bool(
            qualifying_goal
            and qualifying_goal.get("deadline") is not None
            and qualifying_goal["deadline"] <= date.today()
            and (qualifying_goal.get("status") or "").lower() != "completed"
        )
        is_completed_or_due = qualifying_goal is not None

        can_generate_complete = False
        can_generate_in_progress = False
        can_choose_type = False
        reason_blocked = None
        complete_unlock_reason = "not_unlocked"

        if is_completed_or_due:
            can_generate_complete = True
            can_generate_in_progress = True
            can_choose_type = True
            complete_unlock_reason = "completed_goal" if goal_is_completed else "goal_due"
        elif days_of_data >= self.MIN_COMPLETE_DAYS_WITHOUT_GOAL_COMPLETION:
            can_generate_complete = True
            can_generate_in_progress = True
            can_choose_type = True
            complete_unlock_reason = "long_journey"
        elif days_of_data >= self.MIN_IN_PROGRESS_DAYS:
            can_generate_complete = False
            can_generate_in_progress = True
            can_choose_type = False
        else:
            reason_blocked = "Come back after at least 7 days of journey data."

        goal_summary = self._build_goal_summary(goals)
        return {
            "can_generate_complete": can_generate_complete,
            "can_generate_in_progress": can_generate_in_progress,
            "can_choose_type": can_choose_type,
            "days_of_data": days_of_data,
            "journal_days": journal_days,
            "goal_age_days": goal_age_days,
            "goal_completed_or_due": is_completed_or_due,
            "complete_unlock_reason": complete_unlock_reason,
            "minimum_requirements": {
                "in_progress_min_days": self.MIN_IN_PROGRESS_DAYS,
                "complete_min_days_if_goal_not_done_or_due": self.MIN_COMPLETE_DAYS_WITHOUT_GOAL_COMPLETION,
                "uses_journal_entries": True,
                "uses_goal_timeline": True,
            },
            "reason_blocked": reason_blocked,
            "goal_id": str(goal_summary.get("id")) if goal_summary.get("id") else (str(goal_id) if goal_id else None),
            "goal_title": goal_summary.get("title"),
            "goal_ids": [str(goal["id"]) for goal in goals if goal.get("id")],
            "goal_titles": [goal["title"] for goal in goals if goal.get("title")],
            "selection_mode": self.selection_mode,
        }

    def _resolve_selected_goals(
        self,
        *,
        goal_id: str | UUID | None = None,
        goal_ids: list[str | UUID] | None = None,
        include_all_goals: bool = False,
    ) -> dict[str, Any]:
        if include_all_goals:
            selected = self._load_all_goals()
            return {"selected_goals": selected, "selection_mode": "all"}

        if goal_id:
            selected = self._load_goals([goal_id])
            return {"selected_goals": selected, "selection_mode": "single" if selected else "overall"}

        if goal_ids:
            selected = self._load_goals(goal_ids)
            return {
                "selected_goals": selected,
                "selection_mode": "single" if len(selected) == 1 else "multiple",
            }

        return {"selected_goals": [], "selection_mode": "overall"}

    def _load_all_goals(self):
        try:
            from goal.models import Goal

            return list(Goal.objects.filter(user=self.user).order_by("created_at", "id"))
        except Exception:
            return []

    def _load_goals(self, goal_ids: list[str | UUID]):
        try:
            from goal.models import Goal

            ordered_ids: list[str] = []
            for goal_id in goal_ids:
                rendered = str(goal_id)
                if rendered not in ordered_ids:
                    ordered_ids.append(rendered)
            goal_map = {
                str(goal.id): goal
                for goal in Goal.objects.filter(user=self.user, id__in=ordered_ids).order_by("created_at", "id")
            }
            return [goal_map[goal_id] for goal_id in ordered_ids if goal_id in goal_map]
        except Exception:
            return []

    def _get_profile(self) -> dict[str, Any]:
        try:
            profile = getattr(self.user, "profile", None)
            personal = getattr(self.user, "user_personal_details", None)
            return {
                "id": str(self.user.id),
                "email": getattr(self.user, "email", ""),
                "name": getattr(self.user, "username", "") or getattr(self.user, "email", ""),
                "timezone": getattr(profile, "timezone", "UTC") if profile else "UTC",
                "roadmap_start_date": getattr(personal, "roadmap_start_date", None),
                "current_situation": getattr(personal, "current_situation", ""),
            }
        except Exception:
            return {
                "id": str(getattr(self.user, "id", "")),
                "email": getattr(self.user, "email", ""),
                "name": getattr(self.user, "email", ""),
                "timezone": "UTC",
                "roadmap_start_date": None,
                "current_situation": "",
            }

    def _get_goals(self) -> list[dict[str, Any]]:
        goals = []
        for goal in self._selected_goals:
            try:
                deadline = goal.target_date
                created_date = goal.created_at.date() if goal.created_at else None
                goals.append(
                    {
                        "id": goal.id,
                        "title": goal.title,
                        "category": getattr(goal, "primary_category", "personal"),
                        "status": goal.status,
                        "deadline": deadline,
                        "start_date": getattr(goal, "start_date", None),
                        "created_at": created_date,
                    }
                )
            except Exception:
                continue
        return goals

    def _build_goal_summary(self, goals: list[dict[str, Any]]) -> dict[str, Any]:
        if not goals:
            return {}
        if len(goals) == 1:
            return goals[0]

        start_candidates = [goal.get("start_date") or goal.get("created_at") for goal in goals]
        deadline_candidates = [goal.get("deadline") for goal in goals if goal.get("deadline")]
        earliest_start = min((value for value in start_candidates if value), default=None)
        latest_deadline = max(deadline_candidates, default=None)
        return {
            "id": goals[0].get("id"),
            "title": self._goal_collection_title(goals),
            "category": "personal",
            "status": "in_progress",
            "deadline": latest_deadline,
            "start_date": earliest_start,
            "created_at": earliest_start,
        }

    def _goal_collection_title(self, goals: list[dict[str, Any]]) -> str:
        if self.selection_mode == "all":
            return "All goals"
        return f"{len(goals)} goals"

    def _find_complete_unlock_goal(self, goals: list[dict[str, Any]]) -> dict[str, Any] | None:
        if self.selection_mode == "overall":
            return None
        for goal in goals:
            goal_deadline = goal.get("deadline")
            goal_status = (goal.get("status") or "").lower()
            goal_is_completed = goal_status == "completed"
            goal_is_due = goal_deadline is not None and goal_deadline <= date.today()
            if goal_is_completed or goal_is_due:
                return goal
        return None

    def _get_journals(self) -> list[dict[str, Any]]:
        try:
            from journal.models import JournalEntry

            excluded = self.privacy_settings.get("exclude_journal_ids", [])
            qs = JournalEntry.objects.filter(user=self.user)
            if excluded:
                qs = qs.exclude(id__in=excluded)
            qs = qs.order_by("entry_date")

            return list(
                qs.values(
                    "id",
                    "entry_date",
                    "reflection_raw",
                    "struggle_raw",
                    "sentiment_score",
                    "sentiment_label",
                    "tags",
                    "total_word_count",
                )
            )
        except Exception:
            return []

    def _get_streaks(self, journals: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        journals = journals or []
        try:
            from journal.utils import compute_streaks

            dates = [entry["entry_date"] for entry in journals if entry.get("entry_date")]
            streaks = compute_streaks(dates)
            return {
                "current_streak": int(streaks.get("current_streak", 0)),
                "longest_streak": int(streaks.get("longest_streak", 0)),
                "last_entry_date": dates[-1] if dates else None,
            }
        except Exception:
            try:
                dates = sorted([entry["entry_date"] for entry in journals if entry.get("entry_date")])
                return {
                    "current_streak": 0 if not dates else 1,
                    "longest_streak": 0 if not dates else 1,
                    "last_entry_date": dates[-1] if dates else None,
                }
            except Exception:
                return {"current_streak": 0, "longest_streak": 0, "last_entry_date": None}

    def _get_word_frequencies(self) -> dict[str, int]:
        try:
            from journal.models import WordCloudAggregate

            agg = WordCloudAggregate.objects.filter(user=self.user).first()
            return dict(agg.frequencies or {}) if agg else {}
        except Exception:
            return {}

    def _get_existing_derived_milestones(self) -> list[dict[str, Any]]:
        try:
            from journeybook.models import DerivedMilestone

            rows = (
                DerivedMilestone.objects.filter(user=self.user)
                .order_by("achieved_date")
                .values("label", "trigger_type", "achieved_date", "category")
            )
            return list(rows)
        except Exception:
            return []

    @classmethod
    def _calculate_days_of_data(cls, goals: list[dict[str, Any]], journals: list[dict[str, Any]]) -> int:
        return len(cls._combined_date_coverage(goals=goals, journals=journals))

    @classmethod
    def _calculate_data_day_breakdown(
        cls, goals: list[dict[str, Any]], journals: list[dict[str, Any]]
    ) -> tuple[int, int]:
        journal_days = len({entry["entry_date"] for entry in journals if entry.get("entry_date")})
        goal_age_days = len(cls._goal_date_coverage(goals))
        return journal_days, goal_age_days

    @staticmethod
    def _combined_date_coverage(goals: list[dict[str, Any]], journals: list[dict[str, Any]]) -> set[date]:
        return DataCollector._goal_date_coverage(goals).union(
            {entry["entry_date"] for entry in journals if entry.get("entry_date")}
        )

    @staticmethod
    def _goal_date_coverage(goals: list[dict[str, Any]]) -> set[date]:
        covered: set[date] = set()
        today = date.today()
        for goal in goals:
            try:
                start = goal.get("start_date") or goal.get("created_at")
                if not start:
                    continue
                end = goal.get("deadline") or today
                if end < start:
                    end = today
                current = start
                while current <= min(end, today):
                    covered.add(current)
                    current += timedelta(days=1)
            except Exception:
                continue
        return covered

    @staticmethod
    def _infer_selection_mode(selected_goals: list[Any]) -> str:
        if not selected_goals:
            return "overall"
        if len(selected_goals) == 1:
            return "single"
        return "multiple"
