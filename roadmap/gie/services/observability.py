import logging
from statistics import median

from django.db.models import Count
from django.utils import timezone

from gie.models import GIESession, GIESessionAnalytics, GIETurn

logger = logging.getLogger("gie.observability")


class GIEObservabilityService:
    @staticmethod
    def _log_event(event_name: str, payload: dict) -> None:
        logger.info("gie_event=%s payload=%s", event_name, payload)

    @staticmethod
    def _append_completeness_sample(*, analytics: GIESessionAnalytics, completeness: dict | None) -> None:
        if not completeness:
            return
        history = list(analytics.schema_completeness_progress or [])
        history.append(
            {
                "ts": timezone.now().isoformat(),
                "required_slot_count": int(completeness.get("required_slot_count", 0)),
                "filled_required_slot_count": int(completeness.get("filled_required_slot_count", 0)),
                "completeness_percent": float(completeness.get("completeness_percent", 0)),
            }
        )
        analytics.schema_completeness_progress = history

    @classmethod
    def ensure_session_analytics(cls, *, session: GIESession) -> GIESessionAnalytics:
        analytics, _ = GIESessionAnalytics.objects.get_or_create(session=session)
        return analytics

    @classmethod
    def record_session_started(cls, *, session: GIESession, completeness: dict) -> None:
        analytics = cls.ensure_session_analytics(session=session)
        analytics.last_stage = GIESessionAnalytics.STAGE_QUESTION_LOOP
        cls._append_completeness_sample(analytics=analytics, completeness=completeness)
        if session.status in (GIESession.STATUS_READY_TO_FINALIZE, GIESession.STATUS_FINALIZED):
            analytics.plan_review_entered = True
            analytics.turns_to_ready_to_finalize = 0
            analytics.time_to_ready_seconds = 0
            analytics.last_stage = GIESessionAnalytics.STAGE_REVIEW
        analytics.save(update_fields=["last_stage", "schema_completeness_progress", "plan_review_entered", "turns_to_ready_to_finalize", "time_to_ready_seconds", "updated_at"])
        cls._log_event(
            "gie_session_started",
            {
                "session_id": str(session.id),
                "user_id": str(session.user_id),
                "stage": analytics.last_stage,
                "required_slot_count": completeness.get("required_slot_count"),
                "filled_required_slot_count": completeness.get("filled_required_slot_count"),
                "completeness_percent": completeness.get("completeness_percent"),
            },
        )

    @classmethod
    def record_turn_processed(cls, *, session: GIESession, completeness: dict) -> None:
        analytics = cls.ensure_session_analytics(session=session)
        user_turn_count = session.turns.filter(role=GIETurn.ROLE_USER).count()
        analytics.turn_count = user_turn_count
        cls._append_completeness_sample(analytics=analytics, completeness=completeness)
        analytics.last_stage = GIESessionAnalytics.STAGE_QUESTION_LOOP
        if session.status == GIESession.STATUS_READY_TO_FINALIZE:
            analytics.plan_review_entered = True
            analytics.last_stage = GIESessionAnalytics.STAGE_REVIEW
            if analytics.turns_to_ready_to_finalize is None:
                analytics.turns_to_ready_to_finalize = user_turn_count
            if analytics.time_to_ready_seconds is None:
                analytics.time_to_ready_seconds = max(0, int((timezone.now() - session.created_at).total_seconds()))
        analytics.save(
            update_fields=[
                "turn_count",
                "schema_completeness_progress",
                "last_stage",
                "plan_review_entered",
                "turns_to_ready_to_finalize",
                "time_to_ready_seconds",
                "updated_at",
            ]
        )
        cls._log_event(
            "gie_turn_processed",
            {
                "session_id": str(session.id),
                "user_id": str(session.user_id),
                "stage": analytics.last_stage,
                "turn_count": analytics.turn_count,
                "completeness_percent": completeness.get("completeness_percent"),
            },
        )

    @classmethod
    def record_state_read(cls, *, session: GIESession, completeness: dict | None = None) -> None:
        analytics = cls.ensure_session_analytics(session=session)
        if session.status in (GIESession.STATUS_READY_TO_FINALIZE, GIESession.STATUS_FINALIZED):
            analytics.plan_review_entered = True
            analytics.last_stage = GIESessionAnalytics.STAGE_REVIEW
        cls._append_completeness_sample(analytics=analytics, completeness=completeness)
        analytics.save(update_fields=["plan_review_entered", "last_stage", "schema_completeness_progress", "updated_at"])
        cls._log_event(
            "gie_state_read",
            {
                "session_id": str(session.id),
                "user_id": str(session.user_id),
                "stage": analytics.last_stage,
            },
        )

    @classmethod
    def record_finalize_attempt(cls, *, session: GIESession) -> None:
        analytics = cls.ensure_session_analytics(session=session)
        analytics.finalize_attempt_count += 1
        analytics.save(update_fields=["finalize_attempt_count", "updated_at"])
        cls._log_event(
            "gie_finalize_attempt",
            {
                "session_id": str(session.id),
                "user_id": str(session.user_id),
                "finalize_attempt_count": analytics.finalize_attempt_count,
            },
        )

    @classmethod
    def record_finalize_success(cls, *, session: GIESession) -> None:
        analytics = cls.ensure_session_analytics(session=session)
        analytics.plan_accepted = True
        analytics.finalize_success_count += 1
        analytics.last_stage = GIESessionAnalytics.STAGE_FINALIZED
        analytics.drop_off_stage = None
        analytics.time_to_finalize_seconds = max(0, int((timezone.now() - session.created_at).total_seconds()))
        if analytics.turns_to_ready_to_finalize is None:
            analytics.turns_to_ready_to_finalize = session.turns.filter(role=GIETurn.ROLE_USER).count()
        analytics.save(
            update_fields=[
                "plan_accepted",
                "finalize_success_count",
                "last_stage",
                "drop_off_stage",
                "time_to_finalize_seconds",
                "turns_to_ready_to_finalize",
                "updated_at",
            ]
        )
        cls._log_event(
            "gie_finalize_success",
            {
                "session_id": str(session.id),
                "user_id": str(session.user_id),
                "time_to_finalize_seconds": analytics.time_to_finalize_seconds,
                "turns_to_ready_to_finalize": analytics.turns_to_ready_to_finalize,
            },
        )

    @classmethod
    def record_finalize_failure(cls, *, session: GIESession, error_code: str) -> None:
        analytics = cls.ensure_session_analytics(session=session)
        analytics.fallback_activation_count += 1
        analytics.last_fallback_reason_code = error_code
        analytics.last_stage = GIESessionAnalytics.STAGE_FALLBACK
        analytics.drop_off_stage = GIESessionAnalytics.STAGE_REVIEW
        analytics.save(
            update_fields=[
                "fallback_activation_count",
                "last_fallback_reason_code",
                "last_stage",
                "drop_off_stage",
                "updated_at",
            ]
        )
        cls._log_event(
            "gie_finalize_failure",
            {
                "session_id": str(session.id),
                "user_id": str(session.user_id),
                "code": error_code,
                "fallback_activation_count": analytics.fallback_activation_count,
            },
        )

    @classmethod
    def record_adaptation_generated(cls, *, session: GIESession) -> None:
        analytics = cls.ensure_session_analytics(session=session)
        analytics.adaptation_request_count += 1
        analytics.last_stage = GIESessionAnalytics.STAGE_ADAPTATION
        analytics.save(update_fields=["adaptation_request_count", "last_stage", "updated_at"])
        cls._log_event(
            "gie_adaptation_generated",
            {
                "session_id": str(session.id),
                "user_id": str(session.user_id),
                "adaptation_request_count": analytics.adaptation_request_count,
            },
        )

    @classmethod
    def record_policy_block(cls, *, session: GIESession | None, code: str) -> None:
        payload = {"code": code}
        if session:
            analytics = cls.ensure_session_analytics(session=session)
            analytics.degradation_event_count += 1
            analytics.fallback_activation_count += 1
            analytics.last_fallback_reason_code = code
            analytics.last_stage = GIESessionAnalytics.STAGE_BLOCKED
            analytics.drop_off_stage = GIESessionAnalytics.STAGE_FALLBACK
            analytics.save(
                update_fields=[
                    "degradation_event_count",
                    "fallback_activation_count",
                    "last_fallback_reason_code",
                    "last_stage",
                    "drop_off_stage",
                    "updated_at",
                ]
            )
            payload.update(
                {
                    "session_id": str(session.id),
                    "user_id": str(session.user_id),
                    "degradation_event_count": analytics.degradation_event_count,
                }
            )
        cls._log_event("gie_policy_block", payload)

    @staticmethod
    def median_turn_count_to_ready() -> float | None:
        values = list(
            GIESessionAnalytics.objects.filter(turns_to_ready_to_finalize__isnull=False)
            .values_list("turns_to_ready_to_finalize", flat=True)
        )
        if not values:
            return None
        return float(median(values))

    @staticmethod
    def plan_acceptance_rate() -> float:
        total = GIESessionAnalytics.objects.filter(plan_review_entered=True).count()
        if total == 0:
            return 0.0
        accepted = GIESessionAnalytics.objects.filter(plan_review_entered=True, plan_accepted=True).count()
        return round((accepted / total) * 100.0, 2)

    @staticmethod
    def drop_off_distribution() -> dict[str, int]:
        rows = (
            GIESessionAnalytics.objects.filter(drop_off_stage__isnull=False)
            .values("drop_off_stage")
            .annotate(count=Count("id"))
            .order_by("drop_off_stage")
        )
        return {row["drop_off_stage"]: int(row["count"]) for row in rows}
