from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone

from ai.utils.parsers import ResponseParser
from goal.models import Goal
from goal.services.timeline_ai_provider import get_timeline_ai_provider_adapter
from routine.models import DailyTaskItem, DailyTaskList
from routine.progress_services import build_cross_goal_conflict_payload


VALID_KEYS = {
    "plan_health_score",
    "conflicts",
    "at_risk_goals",
    "recommendations",
    "daily_hours_planned",
    "delay_per_missed_day",
    "weekly_success_rate",
    "competing_goals_count",
    "general_note",
}


@dataclass(frozen=True)
class TimelineOverviewContext:
    goals: list[Goal]
    active_goals: list[Goal]
    selected_items: list[DailyTaskItem]
    weekly_success_rate: float | None


class TimelineOverviewInsightService:
    def analyze(self, *, user) -> dict:
        today = timezone.localdate()
        goals = list(
            Goal.objects.filter(user=user)
            .exclude(status="cancelled")
            .order_by("target_date", "created_at")
        )
        active_goals = [
            goal
            for goal in goals
            if goal.status not in {"completed", "cancelled", "paused"}
        ]
        selected_items = self._get_selected_items(user=user, today=today)
        weekly_success_rate = self._get_weekly_success_rate(user=user, today=today)
        context = TimelineOverviewContext(
            goals=goals,
            active_goals=active_goals,
            selected_items=selected_items,
            weekly_success_rate=weekly_success_rate,
        )
        fallback_payload = self._build_deterministic_payload(context=context, today=today)

        try:
            provider_adapter = get_timeline_ai_provider_adapter(max_tokens=900)
        except Exception:
            return fallback_payload

        ai_payload = self._generate_ai_payload(
            provider_adapter=provider_adapter,
            context=context,
            fallback_payload=fallback_payload,
            today=today,
        )
        return ai_payload or fallback_payload

    def _get_selected_items(self, *, user, today):
        task_list = DailyTaskList.objects.filter(user=user, date=today).first()
        if task_list is None:
            return []
        return list(
            DailyTaskItem.objects.filter(task_list=task_list, removed_by_user=False)
            .select_related("related_goal")
            .order_by("display_order", "created_at")
        )

    @staticmethod
    def _get_weekly_success_rate(*, user, today) -> float | None:
        recent = DailyTaskList.objects.filter(
            user=user,
            date__range=(today - timedelta(days=6), today),
        ).aggregate(
            total=Sum("total_tasks"),
            completed=Sum("completed_tasks"),
        )
        total_tasks = int(recent["total"] or 0)
        if total_tasks <= 0:
            return None
        return round(float(recent["completed"] or 0) / float(total_tasks), 2)

    def _build_deterministic_payload(self, *, context: TimelineOverviewContext, today) -> dict:
        conflicts = self._build_conflicts(
            active_goals=context.active_goals,
            selected_items=context.selected_items,
            today=today,
        )
        at_risk_goals = self._build_at_risk_goals(active_goals=context.active_goals, today=today)
        daily_hours_planned = self._build_daily_hours_planned(
            active_goals=context.active_goals,
            selected_items=context.selected_items,
        )
        competing_goals_count = len(context.active_goals) or None
        delay_per_missed_day = self._build_delay_per_missed_day(
            active_goals=context.active_goals,
            weekly_success_rate=context.weekly_success_rate,
        )
        plan_health_score = self._build_plan_health_score(
            active_goals=context.active_goals,
            conflicts=conflicts,
            at_risk_goals=at_risk_goals,
            weekly_success_rate=context.weekly_success_rate,
        )
        recommendations = self._build_recommendations(
            conflicts=conflicts,
            at_risk_goals=at_risk_goals,
            weekly_success_rate=context.weekly_success_rate,
            daily_hours_planned=daily_hours_planned,
        )

        if plan_health_score >= 75:
            general_note = "Your plan looks realistic. Keep this pace."
        elif plan_health_score >= 50:
            general_note = "Your plan is possible, but one bottleneck should be reduced this week."
        else:
            general_note = "Your current plan is overloaded. Reduce scope or extend one deadline."

        return {
            "plan_health_score": plan_health_score,
            "conflicts": conflicts,
            "at_risk_goals": at_risk_goals,
            "recommendations": recommendations,
            "daily_hours_planned": daily_hours_planned,
            "delay_per_missed_day": delay_per_missed_day,
            "weekly_success_rate": context.weekly_success_rate,
            "competing_goals_count": competing_goals_count,
            "general_note": general_note,
        }

    def _build_conflicts(self, *, active_goals: list[Goal], selected_items: list[DailyTaskItem], today) -> list[dict]:
        conflicts: list[dict] = []

        for index, goal_a in enumerate(active_goals):
            start_a = goal_a.start_date or today
            end_a = goal_a.target_date
            if end_a is None:
                continue
            for goal_b in active_goals[index + 1 :]:
                start_b = goal_b.start_date or today
                end_b = goal_b.target_date
                if end_b is None:
                    continue
                overlap_days = self._overlap_days(start_a, end_a, start_b, end_b)
                if overlap_days < 30:
                    continue
                conflicts.append(
                    {
                        "goal_id": str(goal_a.id),
                        "goal_title": goal_a.title,
                        "other_goal_title": goal_b.title,
                        "overlap_days": overlap_days,
                        "description": (
                            f'Potential conflict: "{goal_a.title}" overlaps "{goal_b.title}" '
                            f"for about {overlap_days} days."
                        ),
                    }
                )

        if selected_items:
            routine_conflicts = build_cross_goal_conflict_payload(selected_items)
            active_goal_items = [
                item
                for item in selected_items
                if item.item_type == "goal_task" and item.related_goal_id and not item.is_completed and not item.is_skipped
            ]
            primary_goal_title = active_goal_items[0].related_goal.title if active_goal_items else "Today"
            primary_goal_id = str(active_goal_items[0].related_goal_id) if active_goal_items else None
            for conflict in routine_conflicts.get("conflicts", []):
                evidence = conflict.get("evidence") or {}
                overlap_proxy = int(evidence.get("task_count") or evidence.get("minutes") or 1)
                conflicts.append(
                    {
                        "goal_id": primary_goal_id,
                        "goal_title": primary_goal_title,
                        "other_goal_title": None,
                        "overlap_days": max(1, overlap_proxy),
                        "description": str(conflict.get("message") or "Today's routine has competing goal demand."),
                    }
                )

        return self._dedupe_conflicts(conflicts)[:6]

    def _build_at_risk_goals(self, *, active_goals: list[Goal], today) -> list[dict]:
        results: list[dict] = []
        for goal in active_goals:
            if goal.target_date is None:
                continue
            days_remaining = max(0, (goal.target_date - today).days)
            overdue = goal.target_date < today
            is_at_risk = overdue or (days_remaining <= 30 and int(goal.progress_percentage or 0) < 60)
            if not is_at_risk:
                continue
            results.append(
                {
                    "goal_id": str(goal.id),
                    "goal_title": goal.title,
                    "progress_percentage": int(goal.progress_percentage or 0),
                    "days_remaining": days_remaining,
                    "description": (
                        f"{goal.title} is at risk - {int(goal.progress_percentage or 0)}% done "
                        f"with {days_remaining} day(s) left."
                    ),
                }
            )
        return results[:6]

    @staticmethod
    def _build_daily_hours_planned(*, active_goals: list[Goal], selected_items: list[DailyTaskItem]) -> float:
        pending_minutes = sum(
            int(item.estimated_minutes or 0)
            for item in selected_items
            if not item.is_completed and not item.is_skipped
        )
        if pending_minutes > 0:
            return round(pending_minutes / 60.0, 1)
        if not active_goals:
            return 0.0
        return round(len(active_goals) * 0.75, 1)

    @staticmethod
    def _build_delay_per_missed_day(*, active_goals: list[Goal], weekly_success_rate: float | None) -> int:
        if not active_goals:
            return 0
        base = 3 if len(active_goals) >= 4 else 2 if len(active_goals) >= 2 else 1
        if weekly_success_rate is not None and weekly_success_rate < 0.5:
            base += 1
        return min(5, base)

    @staticmethod
    def _build_plan_health_score(*, active_goals: list[Goal], conflicts: list[dict], at_risk_goals: list[dict], weekly_success_rate: float | None) -> float:
        if not active_goals:
            return 0.0

        average_progress = sum(int(goal.progress_percentage or 0) for goal in active_goals) / len(active_goals)
        base_score = (
            (average_progress / 100.0) * 0.5
            + (0.2 if len(active_goals) <= 3 else 0.08)
            + (0.12 if not conflicts else 0.02)
            + (0.1 if not at_risk_goals else 0.02)
        )
        if weekly_success_rate is not None:
            base_score += weekly_success_rate * 0.18
        score = round(max(10.0, min(95.0, base_score * 100.0)), 1)
        return score

    @staticmethod
    def _build_recommendations(*, conflicts: list[dict], at_risk_goals: list[dict], weekly_success_rate: float | None, daily_hours_planned: float) -> list[dict]:
        recommendations: list[str] = []
        if conflicts:
            recommendations.append("Stagger overlapping goals or move one task block into another day.")
        if at_risk_goals:
            recommendations.append("Pull one at-risk goal into a 7-day recovery sprint with a narrower scope.")
        if weekly_success_rate is not None and weekly_success_rate < 0.6:
            recommendations.append("Raise weekly consistency before adding more work to the timeline.")
        if daily_hours_planned >= 6:
            recommendations.append("Cut or defer at least one low-impact task to keep today sustainable.")
        if not recommendations:
            recommendations.append("Current execution looks stable. Keep your weekly review cadence.")
        return [{"text": text} for text in recommendations[:4]]

    def _generate_ai_payload(self, *, provider_adapter, context: TimelineOverviewContext, fallback_payload: dict, today) -> dict | None:
        prompt = self._build_prompt(context=context, fallback_payload=fallback_payload, today=today, repair=False)
        first_attempt = self._call_and_validate(provider_adapter=provider_adapter, prompt=prompt)
        if first_attempt is not None:
            return first_attempt

        repair_prompt = self._build_prompt(context=context, fallback_payload=fallback_payload, today=today, repair=True)
        return self._call_and_validate(provider_adapter=provider_adapter, prompt=repair_prompt)

    def _call_and_validate(self, *, provider_adapter, prompt: str) -> dict | None:
        try:
            response = provider_adapter.generate_timeline_insight(
                prompt=prompt,
                system_prompt=self._system_prompt(),
            )
            parsed = ResponseParser.parse_json(response.content)
            return self._validate_payload(parsed)
        except Exception:
            return None

    def _build_prompt(self, *, context: TimelineOverviewContext, fallback_payload: dict, today, repair: bool) -> str:
        active_goals_lines = []
        for goal in context.active_goals:
            target_date = goal.target_date.isoformat() if goal.target_date else "none"
            active_goals_lines.append(
                f"- {goal.title} | category={goal.primary_category} | status={goal.status} | "
                f"progress={int(goal.progress_percentage or 0)} | target_date={target_date}"
            )
        selected_items_lines = []
        for item in context.selected_items:
            if item.is_completed or item.is_skipped:
                continue
            selected_items_lines.append(
                f"- {item.title} | goal={item.related_goal.title if item.related_goal_id and item.related_goal else 'none'} | "
                f"priority={item.priority} | minutes={int(item.estimated_minutes or 0)} | slot={item.time_slot or 'unscheduled'}"
            )
        repair_rule = "STRICT REPAIR MODE: return valid JSON only with the exact required keys." if repair else ""
        return "\n\n".join(
            part
            for part in [
                "Create a timeline-level mobile plan health payload for the user's full roadmap.",
                repair_rule,
                f"TODAY: {today.isoformat()}",
                "ACTIVE GOALS",
                "\n".join(active_goals_lines) if active_goals_lines else "No active goals.",
                "TODAY PENDING ROUTINE ITEMS",
                "\n".join(selected_items_lines) if selected_items_lines else "No pending routine items today.",
                f"WEEKLY_SUCCESS_RATE: {context.weekly_success_rate}",
                "DETERMINISTIC FALLBACK PAYLOAD",
                str(fallback_payload),
                self._output_schema(),
            ]
            if part
        )

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You generate read-only timeline health payloads for a mobile app. "
            "Use the provided goals and current routine progress. "
            "Return strict JSON only. Do not add markdown or commentary. "
            "Preserve the exact top-level keys and value types."
        )

    @staticmethod
    def _output_schema() -> str:
        return (
            "Return JSON with exactly these keys: "
            "plan_health_score(number), conflicts(array of objects with goal_title(string), other_goal_title(string|null), "
            "overlap_days(number), description(string), goal_id(string|null)), "
            "at_risk_goals(array of objects with goal_id(string), goal_title(string), progress_percentage(number), "
            "days_remaining(number), description(string)), "
            "recommendations(array of objects with text(string)), daily_hours_planned(number), "
            "delay_per_missed_day(number), weekly_success_rate(number|null), "
            "competing_goals_count(number|null), general_note(string)."
        )

    def _validate_payload(self, payload) -> dict:
        if not isinstance(payload, dict):
            raise ValueError("Timeline overview payload must be an object.")
        if set(payload.keys()) != VALID_KEYS:
            raise ValueError("Timeline overview payload keys do not match the contract.")

        conflicts = payload.get("conflicts")
        at_risk_goals = payload.get("at_risk_goals")
        recommendations = payload.get("recommendations")
        if not isinstance(conflicts, list) or not isinstance(at_risk_goals, list) or not isinstance(recommendations, list):
            raise ValueError("Timeline overview payload collections are invalid.")

        validated_conflicts = []
        for item in conflicts:
            if not isinstance(item, dict):
                raise ValueError("conflicts must contain objects.")
            description = str(item.get("description") or "").strip()
            goal_title = str(item.get("goal_title") or "").strip()
            if not description or not goal_title:
                raise ValueError("conflict items require goal_title and description.")
            other_goal_title = item.get("other_goal_title")
            goal_id = item.get("goal_id")
            validated_conflicts.append(
                {
                    "goal_id": str(goal_id).strip() if goal_id not in (None, "") else None,
                    "goal_title": goal_title,
                    "other_goal_title": str(other_goal_title).strip() if other_goal_title not in (None, "") else None,
                    "overlap_days": max(0, int(float(item.get("overlap_days") or 0))),
                    "description": description,
                }
            )

        validated_risk_goals = []
        for item in at_risk_goals:
            if not isinstance(item, dict):
                raise ValueError("at_risk_goals must contain objects.")
            goal_id = str(item.get("goal_id") or "").strip()
            goal_title = str(item.get("goal_title") or "").strip()
            description = str(item.get("description") or "").strip()
            if not goal_id or not goal_title or not description:
                raise ValueError("at_risk_goals items require goal_id, goal_title, and description.")
            validated_risk_goals.append(
                {
                    "goal_id": goal_id,
                    "goal_title": goal_title,
                    "progress_percentage": max(0, min(100, int(float(item.get("progress_percentage") or 0)))),
                    "days_remaining": max(0, int(float(item.get("days_remaining") or 0))),
                    "description": description,
                }
            )

        validated_recommendations = []
        for item in recommendations:
            if not isinstance(item, dict):
                raise ValueError("recommendations must contain objects.")
            text = str(item.get("text") or "").strip()
            if text:
                validated_recommendations.append({"text": text})

        general_note = str(payload.get("general_note") or "").strip()
        if not general_note:
            raise ValueError("general_note is required.")

        weekly_success_rate = payload.get("weekly_success_rate")
        if weekly_success_rate is not None:
            weekly_success_rate = round(max(0.0, min(1.0, float(weekly_success_rate))), 2)

        competing_goals_count = payload.get("competing_goals_count")
        if competing_goals_count is not None:
            competing_goals_count = max(0, int(float(competing_goals_count)))

        return {
            "plan_health_score": round(max(0.0, min(100.0, float(payload.get("plan_health_score") or 0.0))), 1),
            "conflicts": validated_conflicts,
            "at_risk_goals": validated_risk_goals,
            "recommendations": validated_recommendations[:4],
            "daily_hours_planned": round(max(0.0, float(payload.get("daily_hours_planned") or 0.0)), 1),
            "delay_per_missed_day": max(0, int(float(payload.get("delay_per_missed_day") or 0))),
            "weekly_success_rate": weekly_success_rate,
            "competing_goals_count": competing_goals_count,
            "general_note": general_note,
        }

    @staticmethod
    def _overlap_days(start_a, end_a, start_b, end_b) -> int:
        start = max(start_a, start_b)
        end = min(end_a, end_b)
        if start > end:
            return 0
        return (end - start).days + 1

    @staticmethod
    def _dedupe_conflicts(conflicts: list[dict]) -> list[dict]:
        deduped: list[dict] = []
        seen: set[tuple[str, str | None, str]] = set()
        for item in conflicts:
            key = (
                item.get("goal_title") or "",
                item.get("other_goal_title"),
                item.get("description") or "",
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped
