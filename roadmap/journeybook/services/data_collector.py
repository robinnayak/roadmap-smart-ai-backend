from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID


class DataCollector:
    MIN_IN_PROGRESS_DAYS = 7
    MIN_COMPLETE_DAYS_WITHOUT_GOAL_COMPLETION = 180

    def __init__(self, user, goal_id: str | UUID | None = None, privacy_settings: dict | None = None):
        self.user = user
        self.goal_id = goal_id
        self.privacy_settings = privacy_settings or {}

    def collect_all_data(self) -> dict[str, Any]:
        goal = self._get_goal(self.goal_id)
        journals = self._get_journals()
        streaks = self._get_streaks(journals=journals)

        return {
            "user": self.user,
            "profile": self._get_profile(),
            "goal": goal,
            "journals": journals,
            "streaks": streaks,
            "word_frequencies": self._get_word_frequencies(),
            "derived_milestones": self._get_existing_derived_milestones(),
        }

    def check_eligibility(self, goal_id: str | UUID | None = None) -> dict[str, Any]:
        goal = self._get_goal(goal_id)
        journals = self._get_journals()
        journal_days, goal_age_days = self._calculate_data_day_breakdown(goal=goal, journals=journals)
        days_of_data = max(journal_days, goal_age_days)

        goal_deadline = goal.get("deadline")
        goal_status = (goal.get("status") or "").lower()
        goal_is_completed = goal_status == "completed"
        goal_is_due = goal_deadline is not None and goal_deadline <= date.today()
        is_completed_or_due = goal_is_completed or goal_is_due

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
            "goal_id": str(goal.get("id")) if goal.get("id") else (str(goal_id) if goal_id else None),
            "goal_title": goal.get("title"),
        }

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

    def _get_goal(self, goal_id: str | UUID | None) -> dict[str, Any]:
        if not goal_id:
            return {}
        try:
            from goal.models import Goal

            goal = Goal.objects.filter(id=goal_id, user=self.user).first()
            if not goal:
                return {}
            deadline = goal.target_date
            created_date = goal.created_at.date() if goal.created_at else None
            return {
                "id": goal.id,
                "title": goal.title,
                "category": getattr(goal, "primary_category", "personal"),
                "status": goal.status,
                "deadline": deadline,
                "start_date": getattr(goal, "start_date", None),
                "created_at": created_date,
            }
        except (ImportError, Exception):
            return {}

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
        except (ImportError, Exception):
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
        except (ImportError, Exception):
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
        except (ImportError, Exception):
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

    @staticmethod
    def _calculate_days_of_data(goal: dict[str, Any], journals: list[dict[str, Any]]) -> int:
        journal_days, goal_age_days = DataCollector._calculate_data_day_breakdown(goal=goal, journals=journals)
        return max(journal_days, goal_age_days)

    @staticmethod
    def _calculate_data_day_breakdown(goal: dict[str, Any], journals: list[dict[str, Any]]) -> tuple[int, int]:
        journal_days = len({entry["entry_date"] for entry in journals if entry.get("entry_date")})

        goal_age_days = 0
        try:
            start = goal.get("start_date") or goal.get("created_at")
            if start:
                goal_age_days = max((date.today() - start).days + 1, 0)
        except Exception:
            goal_age_days = 0

        return journal_days, goal_age_days
