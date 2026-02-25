from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from statistics import mean
from typing import Any


class MetricsCalculator:
    def __init__(self, collected_data: dict[str, Any]):
        self.collected_data = collected_data or {}
        self.user = self.collected_data.get("user")
        self.goal = self.collected_data.get("goal") or {}
        self.streaks = self.collected_data.get("streaks") or {}
        self.journals = sorted(
            self.collected_data.get("journals") or [],
            key=lambda row: row.get("entry_date") or date.min,
        )

    def calculate_all(self) -> dict[str, Any]:
        dip = self.dip_detection(self.journals)
        comeback = self.comeback_detection(self.journals, dip)
        hardest = self.hardest_days(self.journals)
        wins = self.invisible_wins(self.journals, self.streaks)
        derived = self.derive_milestones(self.journals, self.goal, self.streaks)
        projections = self.projections(self.journals, self.goal)

        completion_trend = float(projections.get("completion_trend", 0.0))
        sentiment_trend = float(projections.get("sentiment_trend", 0.0))

        sentiment_values = [self._safe_float(j.get("sentiment_score")) for j in self.journals]
        overview = {
            "start_date": self.journals[0]["entry_date"] if self.journals else None,
            "end_date": self.journals[-1]["entry_date"] if self.journals else None,
            "total_entries": len(self.journals),
            "avg_sentiment": round(mean(sentiment_values), 3) if sentiment_values else 0.0,
            "days_of_data": len({j["entry_date"] for j in self.journals if j.get("entry_date")}),
        }

        return {
            "journey_overview": overview,
            "dip": dip,
            "comeback": comeback,
            "hardest_days": hardest,
            "invisible_wins": wins,
            "derived_milestones": derived,
            "behavioral_patterns": self._behavioral_patterns(self.journals),
            "completion_trend": completion_trend,
            "sentiment_trend": sentiment_trend,
            "projections": projections,
            "journals": self.journals,
            "goal": self.goal,
        }

    def dip_detection(self, journals: list[dict[str, Any]]) -> dict[str, Any]:
        if not journals:
            return {
                "dip_start_date": None,
                "dip_end_date": None,
                "days_missed": 0,
                "dip_type": "none",
                "severity": 0.0,
            }

        longest_gap = None
        for prev, curr in zip(journals, journals[1:]):
            prev_date = prev.get("entry_date")
            curr_date = curr.get("entry_date")
            if not prev_date or not curr_date:
                continue
            gap_days = (curr_date - prev_date).days - 1
            if gap_days >= 3:
                gap = {
                    "dip_start_date": prev_date + timedelta(days=1),
                    "dip_end_date": curr_date - timedelta(days=1),
                    "days_missed": gap_days,
                    "dip_type": "missed_days",
                    "severity": float(gap_days),
                }
                if longest_gap is None or gap["days_missed"] > longest_gap["days_missed"]:
                    longest_gap = gap

        if longest_gap:
            return longest_gap

        if len(journals) >= 7:
            best_window = None
            for i in range(0, len(journals) - 6):
                window = journals[i : i + 7]
                avg = mean(self._safe_float(item.get("sentiment_score")) for item in window)
                if best_window is None or avg < best_window["avg"]:
                    best_window = {"window": window, "avg": avg}
            window = best_window["window"]
            return {
                "dip_start_date": window[0].get("entry_date"),
                "dip_end_date": window[-1].get("entry_date"),
                "days_missed": 0,
                "dip_type": "low_sentiment",
                "severity": abs(float(best_window["avg"])),
            }

        avg = mean(self._safe_float(item.get("sentiment_score")) for item in journals)
        return {
            "dip_start_date": journals[0].get("entry_date"),
            "dip_end_date": journals[-1].get("entry_date"),
            "days_missed": 0,
            "dip_type": "low_sentiment",
            "severity": abs(float(avg)),
        }

    def comeback_detection(self, journals: list[dict[str, Any]], dip: dict[str, Any]) -> dict[str, Any]:
        if not journals:
            return {"comeback_date": None, "days_missed_before": 0, "entry_snippet": ""}

        dip_end = dip.get("dip_end_date")
        if dip_end:
            for entry in journals:
                entry_date = entry.get("entry_date")
                if entry_date and entry_date > dip_end:
                    return {
                        "comeback_date": entry_date,
                        "days_missed_before": int(dip.get("days_missed", 0)),
                        "entry_snippet": self._entry_snippet(entry, 150),
                    }

        for prev, curr in zip(journals, journals[1:]):
            prev_date = prev.get("entry_date")
            curr_date = curr.get("entry_date")
            if not prev_date or not curr_date:
                continue
            gap_days = (curr_date - prev_date).days - 1
            if gap_days >= 2:
                return {
                    "comeback_date": curr_date,
                    "days_missed_before": gap_days,
                    "entry_snippet": self._entry_snippet(curr, 150),
                }

        fallback = min(journals, key=lambda x: self._safe_float(x.get("sentiment_score")))
        return {
            "comeback_date": fallback.get("entry_date"),
            "days_missed_before": 0,
            "entry_snippet": self._entry_snippet(fallback, 150),
        }

    def hardest_days(self, journals: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not journals:
            return []

        candidates = [
            entry
            for entry in journals
            if len((entry.get("reflection_raw") or "").strip()) >= 20
        ]
        candidates.sort(key=lambda x: self._safe_float(x.get("sentiment_score")))

        selected: list[dict[str, Any]] = []
        for entry in candidates:
            entry_date = entry.get("entry_date")
            if not entry_date:
                continue
            if any(abs((entry_date - picked["date"]).days) < 7 for picked in selected):
                continue
            selected.append(
                {
                    "date": entry_date,
                    "sentiment_score": self._safe_float(entry.get("sentiment_score")),
                    "reflection_snippet": self._entry_snippet(entry, 180),
                }
            )
            if len(selected) == 3:
                break
        return selected

    def invisible_wins(self, journals: list[dict[str, Any]], streaks: dict[str, Any]) -> list[dict[str, Any]]:
        wins: list[dict[str, Any]] = []

        low_entries = [
            e for e in journals if self._safe_float(e.get("sentiment_score")) < -0.2
        ]
        for entry in low_entries[:6]:
            wins.append(
                {
                    "label": "Showed up low",
                    "date": entry.get("entry_date"),
                    "detail": "You still journaled on a hard emotional day.",
                }
            )

        if streaks.get("current_streak", 0) >= 7 and self._find_any_gap(journals, min_gap=2):
            wins.append(
                {
                    "label": "Streak rebuilt",
                    "date": streaks.get("last_entry_date"),
                    "detail": "You rebuilt consistency after a reset.",
                }
            )

        for prev, curr in zip(journals, journals[1:]):
            prev_date = prev.get("entry_date")
            curr_date = curr.get("entry_date")
            if not prev_date or not curr_date:
                continue
            gap_days = (curr_date - prev_date).days - 1
            if gap_days >= 3:
                week_end = curr_date + timedelta(days=6)
                week_entries = [
                    row
                    for row in journals
                    if row.get("entry_date") and curr_date <= row["entry_date"] <= week_end
                ]
                if week_entries:
                    completion_ratio = mean(
                        1.0 if self._safe_float(row.get("sentiment_score")) >= 0.0 else 0.0
                        for row in week_entries
                    )
                    if completion_ratio >= 0.7:
                        wins.append(
                            {
                                "label": "Consistent despite gap",
                                "date": curr_date,
                                "detail": "Your week-after-gap consistency stayed strong.",
                            }
                        )
                        break

        weekly_counts: dict[tuple[int, int], int] = defaultdict(int)
        for entry in journals:
            entry_date = entry.get("entry_date")
            if not entry_date:
                continue
            year, week, _ = entry_date.isocalendar()
            weekly_counts[(year, week)] += int(entry.get("total_word_count") or 0)

        if weekly_counts:
            avg_weekly_words = mean(weekly_counts.values())
            for (year, week), total_words in sorted(weekly_counts.items()):
                if avg_weekly_words > 0 and total_words > 2 * avg_weekly_words:
                    approx_date = date.fromisocalendar(year, week, 1)
                    wins.append(
                        {
                            "label": "Volume surge",
                            "date": approx_date,
                            "detail": "You wrote over 2x your weekly average.",
                        }
                    )
                    break

        deduped = []
        seen = set()
        for win in wins:
            key = (win.get("label"), win.get("date"))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(win)
            if len(deduped) >= 12:
                break
        return deduped

    def projections(self, journals: list[dict[str, Any]], goal: dict[str, Any]) -> dict[str, Any]:
        window = journals[-30:] if len(journals) > 30 else journals
        if not window:
            return {
                "completion_trend": 0.0,
                "sentiment_trend": 0.0,
                "completion_projection": "Not enough data to project completion yet.",
                "sentiment_trajectory": "Not enough data to project sentiment yet.",
                "projected_completion_date": None,
            }

        completion_series = [
            1.0 if self._safe_float(item.get("sentiment_score")) >= 0 else 0.0
            for item in window
        ]
        sentiment_series = [self._safe_float(item.get("sentiment_score")) for item in window]

        completion_slope = self._linear_regression_slope(completion_series)
        sentiment_slope = self._linear_regression_slope(sentiment_series)

        deadline = goal.get("deadline")
        days_to_deadline = 0
        if deadline:
            days_to_deadline = max((deadline - date.today()).days, 0)

        last_completion = completion_series[-1]
        projected_completion = max(
            0.0,
            min(1.0, last_completion + (completion_slope * days_to_deadline)),
        )
        projected_completion_pct = round(projected_completion * 100, 1)

        last_sentiment = sentiment_series[-1]
        projected_sentiment = last_sentiment + (sentiment_slope * days_to_deadline)
        projected_sentiment = round(max(-1.0, min(1.0, projected_sentiment)), 3)

        projected_completion_date = None
        if completion_slope > 0 and last_completion < 1.0:
            days_needed = int((1.0 - last_completion) / completion_slope)
            if days_needed >= 0:
                projected_completion_date = date.today() + timedelta(days=days_needed)

        deadline_text = deadline.isoformat() if deadline else "your next milestone"
        return {
            "completion_trend": float(round(completion_slope, 6)),
            "sentiment_trend": float(round(sentiment_slope, 6)),
            "completion_projection": (
                f"At your current pace, by {deadline_text} you could reach about "
                f"{projected_completion_pct}% consistency."
            ),
            "sentiment_trajectory": (
                f"Your emotional trend suggests a projected sentiment around {projected_sentiment} "
                f"if current patterns continue."
            ),
            "projected_completion_date": projected_completion_date,
        }

    def derive_milestones(
        self,
        journals: list[dict[str, Any]],
        goal: dict[str, Any],
        streaks: dict[str, Any],
    ) -> list[dict[str, Any]]:
        milestones: list[dict[str, Any]] = []

        if journals:
            first_date = journals[0].get("entry_date")
            if first_date:
                milestones.append(
                    {
                        "label": "The First Step",
                        "trigger_type": "first_journal_entry",
                        "achieved_date": first_date,
                        "category": "writing",
                    }
                )

        last_entry = journals[-1].get("entry_date") if journals else None
        longest_streak = int(streaks.get("longest_streak", 0) or 0)
        if longest_streak >= 7:
            milestones.append(
                {
                    "label": "One Week In",
                    "trigger_type": "streak_7",
                    "achieved_date": last_entry,
                    "category": "discipline",
                }
            )
        if longest_streak >= 30:
            milestones.append(
                {
                    "label": "A Month of Discipline",
                    "trigger_type": "streak_30",
                    "achieved_date": last_entry,
                    "category": "discipline",
                }
            )
        if longest_streak >= 100:
            milestones.append(
                {
                    "label": "Century Mark",
                    "trigger_type": "streak_100",
                    "achieved_date": last_entry,
                    "category": "discipline",
                }
            )

        if len(journals) >= 50 and last_entry:
            milestones.append(
                {
                    "label": "50 Stories Written",
                    "trigger_type": "journal_50_entries",
                    "achieved_date": last_entry,
                    "category": "writing",
                }
            )

        cross_date = self._find_avg_sentiment_cross_date(journals, threshold=0.3)
        if cross_date:
            milestones.append(
                {
                    "label": "Turning the Corner",
                    "trigger_type": "avg_sentiment_cross_0_3",
                    "achieved_date": cross_date,
                    "category": "personal",
                }
            )

        first_subgoal_win = self._first_completed_subgoal_date()
        if first_subgoal_win:
            milestones.append(
                {
                    "label": "First Win",
                    "trigger_type": "first_completed_subgoal",
                    "achieved_date": first_subgoal_win,
                    "category": goal.get("category") or "personal",
                }
            )

        milestones = [m for m in milestones if m.get("achieved_date")]
        milestones.sort(key=lambda x: x["achieved_date"])

        self._upsert_derived_milestones(milestones)
        return milestones

    @staticmethod
    def _behavioral_patterns(journals: list[dict[str, Any]]) -> dict[str, Any]:
        if not journals:
            return {
                "sentiment_volatility": 0.0,
                "avg_words_per_entry": 0.0,
                "entries_per_week_estimate": 0.0,
            }
        sentiments = [float(item.get("sentiment_score") or 0.0) for item in journals]
        words = [int(item.get("total_word_count") or 0) for item in journals]
        volatility = max(sentiments) - min(sentiments) if sentiments else 0.0
        valid_dates = [item.get("entry_date") for item in journals if item.get("entry_date")]
        if valid_dates:
            day_span = (max(valid_dates) - min(valid_dates)).days + 1
        else:
            day_span = len(journals)
        weeks = max(day_span / 7.0, 1.0)
        return {
            "sentiment_volatility": round(volatility, 3),
            "avg_words_per_entry": round(mean(words), 1) if words else 0.0,
            "entries_per_week_estimate": round(len(journals) / weeks, 2),
        }

    @staticmethod
    def _linear_regression_slope(values: list[float]) -> float:
        n = len(values)
        if n < 2:
            return 0.0
        x_values = list(range(n))
        sum_x = sum(x_values)
        sum_y = sum(values)
        sum_xy = sum(x * y for x, y in zip(x_values, values))
        sum_x2 = sum(x * x for x in x_values)
        denominator = n * sum_x2 - (sum_x * sum_x)
        if denominator == 0:
            return 0.0
        return (n * sum_xy - sum_x * sum_y) / denominator

    @staticmethod
    def _safe_float(value: Any) -> float:
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _entry_snippet(entry: dict[str, Any], limit: int = 150) -> str:
        text = (entry.get("reflection_raw") or "").strip()
        if not text:
            text = (entry.get("struggle_raw") or "").strip()
        return text[:limit]

    @staticmethod
    def _find_any_gap(journals: list[dict[str, Any]], min_gap: int) -> bool:
        for prev, curr in zip(journals, journals[1:]):
            prev_date = prev.get("entry_date")
            curr_date = curr.get("entry_date")
            if not prev_date or not curr_date:
                continue
            if (curr_date - prev_date).days - 1 >= min_gap:
                return True
        return False

    @staticmethod
    def _find_avg_sentiment_cross_date(journals: list[dict[str, Any]], threshold: float) -> date | None:
        running = 0.0
        for index, entry in enumerate(journals, start=1):
            running += float(entry.get("sentiment_score") or 0.0)
            if (running / index) > threshold:
                return entry.get("entry_date")
        return None

    def _first_completed_subgoal_date(self) -> date | None:
        try:
            from goal.models import SubGoal

            subgoal = (
                SubGoal.objects.filter(
                    milestone__goal__user=self.user,
                    status="completed",
                )
                .order_by("completed_date", "updated_at")
                .first()
            )
            if not subgoal:
                return None
            return subgoal.completed_date or subgoal.updated_at.date()
        except (ImportError, Exception):
            return None

    def _upsert_derived_milestones(self, milestones: list[dict[str, Any]]) -> None:
        if not self.user or not milestones:
            return
        try:
            from journeybook.models import DerivedMilestone
        except Exception:
            return

        for milestone in milestones:
            trigger_type = milestone["trigger_type"]
            defaults = {
                "label": milestone["label"],
                "achieved_date": milestone["achieved_date"],
                "category": milestone.get("category", "personal"),
            }
            try:
                obj, created = DerivedMilestone.objects.get_or_create(
                    user=self.user,
                    trigger_type=trigger_type,
                    defaults=defaults,
                )
                if not created:
                    updated = False
                    for key, value in defaults.items():
                        if getattr(obj, key) != value:
                            setattr(obj, key, value)
                            updated = True
                    if updated:
                        obj.save(update_fields=["label", "achieved_date", "category"])
            except Exception:
                continue
