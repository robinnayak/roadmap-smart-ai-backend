from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.apps import apps
from django.db.models import Max
from django.utils import timezone

from ai.models import AIReengagementAction, AIUserChurnState


@dataclass
class ChurnScoreResult:
    risk_score: float
    risk_tier: str
    inactivity_days: int
    last_activity_at: object
    score_inputs: dict


class ChurnReengagementService:
    RISK_THRESHOLD_MEDIUM = 40.0
    RISK_THRESHOLD_HIGH = 70.0
    COOLDOWN_HOURS = 24

    def score_user(self, user) -> ChurnScoreResult:
        now = timezone.now()
        last_activity_at = self._get_last_activity_at(user=user)

        if last_activity_at is None:
            inactivity_days = 365
        else:
            inactivity_days = max(0, (now - last_activity_at).days)

        routine_activity_3d = self._has_recent_activity(
            app_label="routine",
            model_name="DailyTaskList",
            user=user,
            timestamp_field="updated_at",
            days=3,
        )
        journal_activity_7d = self._has_recent_activity(
            app_label="journal",
            model_name="JournalEntry",
            user=user,
            timestamp_field="updated_at",
            days=7,
        )

        base_score = self._score_by_inactivity_days(inactivity_days)
        penalty = 0.0
        if not routine_activity_3d:
            penalty += 8.0
        if not journal_activity_7d:
            penalty += 5.0
        if inactivity_days >= 3 and not self._has_positive_streak(user=user):
            penalty += 5.0

        risk_score = min(100.0, base_score + penalty)
        risk_tier = self._tier_for_score(risk_score)

        return ChurnScoreResult(
            risk_score=risk_score,
            risk_tier=risk_tier,
            inactivity_days=inactivity_days,
            last_activity_at=last_activity_at,
            score_inputs={
                "base_score": base_score,
                "penalty": penalty,
                "routine_activity_3d": routine_activity_3d,
                "journal_activity_7d": journal_activity_7d,
            },
        )

    def process_user(self, user) -> dict:
        score_result = self.score_user(user=user)
        churn_state, _ = AIUserChurnState.objects.get_or_create(
            user=user,
            defaults={
                "risk_score": score_result.risk_score,
                "risk_tier": score_result.risk_tier,
                "inactivity_days": score_result.inactivity_days,
                "last_activity_at": score_result.last_activity_at,
                "score_inputs": score_result.score_inputs,
            },
        )

        churn_state.risk_score = score_result.risk_score
        churn_state.risk_tier = score_result.risk_tier
        churn_state.inactivity_days = score_result.inactivity_days
        churn_state.last_activity_at = score_result.last_activity_at
        churn_state.last_scored_at = timezone.now()
        churn_state.score_inputs = score_result.score_inputs
        churn_state.save(
            update_fields=[
                "risk_score",
                "risk_tier",
                "inactivity_days",
                "last_activity_at",
                "last_scored_at",
                "score_inputs",
                "updated_at",
            ]
        )

        if score_result.risk_tier == AIUserChurnState.RISK_TIER_LOW:
            return {"risk_tier": score_result.risk_tier, "action": "none", "status": "not_required"}

        action_type = self._resolve_action_type(user=user, risk_tier=score_result.risk_tier)
        return self._orchestrate_action(user=user, churn_state=churn_state, action_type=action_type)

    def _orchestrate_action(self, *, user, churn_state: AIUserChurnState, action_type: str) -> dict:
        if self._is_reengaged(user=user):
            action = AIReengagementAction.objects.create(
                user=user,
                churn_state=churn_state,
                action_type=action_type,
                channel=AIReengagementAction.CHANNEL_NONE,
                status=AIReengagementAction.STATUS_REENGAGED_BLOCKED,
                reason_code="recent_activity_detected",
                risk_score=churn_state.risk_score,
                risk_tier=churn_state.risk_tier,
                metadata={"cooldown_hours": self.COOLDOWN_HOURS},
            )
            return {"risk_tier": churn_state.risk_tier, "action": action.action_type, "status": action.status}

        if self._is_in_cooldown(user=user, action_type=action_type):
            action = AIReengagementAction.objects.create(
                user=user,
                churn_state=churn_state,
                action_type=action_type,
                channel=AIReengagementAction.CHANNEL_NONE,
                status=AIReengagementAction.STATUS_COOLDOWN_BLOCKED,
                reason_code="cooldown_active",
                risk_score=churn_state.risk_score,
                risk_tier=churn_state.risk_tier,
                metadata={"cooldown_hours": self.COOLDOWN_HOURS},
            )
            return {"risk_tier": churn_state.risk_tier, "action": action.action_type, "status": action.status}

        channel, suppressed_reason = self._resolve_channel(user=user)
        if channel is None:
            action = AIReengagementAction.objects.create(
                user=user,
                churn_state=churn_state,
                action_type=action_type,
                channel=AIReengagementAction.CHANNEL_NONE,
                status=AIReengagementAction.STATUS_SUPPRESSED,
                reason_code=suppressed_reason or "notifications_not_allowed",
                risk_score=churn_state.risk_score,
                risk_tier=churn_state.risk_tier,
                metadata={"cooldown_hours": self.COOLDOWN_HOURS},
            )
            return {"risk_tier": churn_state.risk_tier, "action": action.action_type, "status": action.status}

        message_payload = self._build_message_payload(
            user=user,
            churn_state=churn_state,
            action_type=action_type,
            channel=channel,
        )
        action = AIReengagementAction.objects.create(
            user=user,
            churn_state=churn_state,
            action_type=action_type,
            channel=channel,
            status=AIReengagementAction.STATUS_SENT,
            reason_code="delivered",
            risk_score=churn_state.risk_score,
            risk_tier=churn_state.risk_tier,
            metadata={
                "cooldown_hours": self.COOLDOWN_HOURS,
                "message_payload": message_payload,
            },
        )
        return {"risk_tier": churn_state.risk_tier, "action": action.action_type, "status": action.status}

    @staticmethod
    def _build_message_payload(*, user, churn_state: AIUserChurnState, action_type: str, channel: str) -> dict:
        first_name = (
            (getattr(user, "first_name", "") or "").strip()
            or (getattr(user, "email", "") or "there").split("@")[0]
            or "there"
        )
        risk_label = churn_state.risk_tier.replace("_", " ").title()
        inactivity_days = max(churn_state.inactivity_days, 0)

        if action_type == AIReengagementAction.ACTION_TYPE_ESCALATION:
            headline = f"{first_name}, let's get your momentum back today."
            body = (
                f"Your planner has been inactive for {inactivity_days} days. "
                "Start with one focused task to restart progress."
            )
            cta_label = "Restart With One Task"
        else:
            headline = f"Quick check-in, {first_name}."
            body = (
                f"You've been away for {inactivity_days} days. "
                "A small action now keeps your roadmap moving."
            )
            cta_label = "Open Today's Plan"

        return {
            "channel": channel,
            "action_type": action_type,
            "risk_tier": churn_state.risk_tier,
            "risk_score": round(churn_state.risk_score, 1),
            "headline": headline,
            "body": body,
            "cta": {
                "label": cta_label,
                "target": "/routine",
            },
            "tags": [risk_label.lower(), action_type],
        }

    def _resolve_channel(self, *, user) -> tuple[str | None, str | None]:
        NotificationSettings = apps.get_model("authentication", "NotificationSettings")
        settings_obj = NotificationSettings.objects.filter(user=user).first()
        if settings_obj is None:
            return AIReengagementAction.CHANNEL_PUSH, None

        if not settings_obj.notifications_enabled:
            return None, "notifications_disabled"
        if not settings_obj.personalize_assistant:
            return None, "assistant_disabled"
        if settings_obj.push_notifications:
            return AIReengagementAction.CHANNEL_PUSH, None
        if settings_obj.email_notifications:
            return AIReengagementAction.CHANNEL_EMAIL, None
        return None, "channel_disabled"

    def _resolve_action_type(self, *, user, risk_tier: str) -> str:
        if risk_tier != AIUserChurnState.RISK_TIER_HIGH:
            return AIReengagementAction.ACTION_TYPE_NUDGE

        previous_nudge_exists = AIReengagementAction.objects.filter(
            user=user,
            action_type=AIReengagementAction.ACTION_TYPE_NUDGE,
            status=AIReengagementAction.STATUS_SENT,
        ).exists()
        return (
            AIReengagementAction.ACTION_TYPE_ESCALATION
            if previous_nudge_exists
            else AIReengagementAction.ACTION_TYPE_NUDGE
        )

    def _is_in_cooldown(self, *, user, action_type: str) -> bool:
        window_start = timezone.now() - timedelta(hours=self.COOLDOWN_HOURS)
        return AIReengagementAction.objects.filter(
            user=user,
            action_type=action_type,
            status=AIReengagementAction.STATUS_SENT,
            created_at__gte=window_start,
        ).exists()

    def _is_reengaged(self, *, user) -> bool:
        last_activity = self._get_last_activity_at(user=user)
        if last_activity is None:
            return False
        return last_activity >= timezone.now() - timedelta(hours=self.COOLDOWN_HOURS)

    @staticmethod
    def _tier_for_score(score: float) -> str:
        if score < ChurnReengagementService.RISK_THRESHOLD_MEDIUM:
            return AIUserChurnState.RISK_TIER_LOW
        if score < ChurnReengagementService.RISK_THRESHOLD_HIGH:
            return AIUserChurnState.RISK_TIER_MEDIUM
        return AIUserChurnState.RISK_TIER_HIGH

    @staticmethod
    def _score_by_inactivity_days(inactivity_days: int) -> float:
        if inactivity_days <= 1:
            return 10.0
        if inactivity_days <= 2:
            return 25.0
        if inactivity_days <= 3:
            return 45.0
        if inactivity_days <= 5:
            return 65.0
        if inactivity_days <= 7:
            return 80.0
        return 92.0

    def _get_last_activity_at(self, *, user):
        candidates = [user.last_login]
        candidates.extend(self._get_activity_timestamps(user=user))
        filtered = [value for value in candidates if value is not None]
        return max(filtered) if filtered else None

    def _get_activity_timestamps(self, *, user) -> list:
        targets = [
            ("routine", "DailyTaskItem", "updated_at", "task_list__user"),
            ("routine", "DailyTaskList", "updated_at", "user"),
            ("routine", "HabitCompletion", "created_at", "user"),
            ("journal", "JournalEntry", "updated_at", "user"),
            ("ai", "AIProcessingJob", "updated_at", "user"),
        ]
        values = []
        for app_label, model_name, field_name, user_lookup in targets:
            value = self._max_timestamp(
                app_label=app_label,
                model_name=model_name,
                user=user,
                timestamp_field=field_name,
                user_lookup=user_lookup,
            )
            if value is not None:
                values.append(value)
        return values

    def _max_timestamp(
        self,
        *,
        app_label: str,
        model_name: str,
        user,
        timestamp_field: str,
        user_lookup: str = "user",
    ):
        try:
            model = apps.get_model(app_label, model_name)
        except LookupError:
            return None

        return model.objects.filter(**{user_lookup: user}).aggregate(value=Max(timestamp_field)).get("value")

    def _has_recent_activity(
        self,
        *,
        app_label: str,
        model_name: str,
        user,
        timestamp_field: str,
        days: int,
    ) -> bool:
        threshold = timezone.now() - timedelta(days=days)
        timestamp = self._max_timestamp(
            app_label=app_label,
            model_name=model_name,
            user=user,
            timestamp_field=timestamp_field,
            user_lookup="user",
        )
        return bool(timestamp and timestamp >= threshold)

    @staticmethod
    def _has_positive_streak(*, user) -> bool:
        try:
            DisciplineStreak = apps.get_model("routine", "DisciplineStreak")
        except LookupError:
            return False

        streak = DisciplineStreak.objects.filter(user=user).first()
        return bool(streak and streak.current_streak_days > 0)
