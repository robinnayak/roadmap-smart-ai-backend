from datetime import timedelta

from django.utils import timezone

from gie.models import GIEAdaptationProposal, GIESession


class GIEAdaptationService:
    TRIGGER_PRIORITY = {
        "missed_tasks_streak": 1,
        "declining_engagement": 2,
        "negative_sentiment": 3,
        "stalled_progress": 4,
        "timeline_change": 5,
    }

    @classmethod
    def generate_proposal_payload(cls, *, session: GIESession, signals: list[dict]) -> dict:
        sorted_signals = sorted(
            signals,
            key=lambda item: cls.TRIGGER_PRIORITY.get(item.get("trigger"), 99),
        )
        primary = sorted_signals[0]
        trigger = primary["trigger"]

        if trigger == GIEAdaptationProposal.TRIGGER_MISSED_TASKS_STREAK:
            action = GIEAdaptationProposal.ACTION_REDUCE_SCOPE
            reason = "Consecutive misses indicate plan overload under current constraints."
            changes = cls._build_reduce_scope_changes(session=session)
        elif trigger == GIEAdaptationProposal.TRIGGER_DECLINING_ENGAGEMENT:
            action = GIEAdaptationProposal.ACTION_INCREASE_SUPPORT
            reason = "Declining engagement suggests adding accountability and lighter checkpoints."
            changes = [
                {"target": "weekly_review_cadence", "before": "weekly", "after": "twice_weekly"},
                {"target": "support_channel", "before": "self", "after": "guided"},
            ]
        elif trigger == GIEAdaptationProposal.TRIGGER_NEGATIVE_SENTIMENT:
            action = GIEAdaptationProposal.ACTION_SWAP_COMMITMENT
            reason = "Negative sentiment indicates current commitment framing may be too rigid."
            changes = [
                {"target": "commitment_style", "before": "strict", "after": "flexible"},
            ]
        elif trigger == GIEAdaptationProposal.TRIGGER_TIMELINE_CHANGE:
            action = GIEAdaptationProposal.ACTION_ADJUST_TIMELINE
            reason = "Timeline change request requires extending milestone windows."
            changes = cls._build_timeline_changes(session=session)
        else:
            action = GIEAdaptationProposal.ACTION_RESEQUENCE_MILESTONES
            reason = "Progress is stalled; re-sequencing milestones can restore momentum."
            changes = [
                {"target": "milestone_order", "before": "current_sequence", "after": "dependency_first_sequence"},
            ]

        recommended_commitment_updates = [
            {
                "commitment_id": "c1",
                "proposed_statement": "I commit to a smaller, consistent weekly execution target for the next 3 weeks.",
            }
        ]

        return {
            "trigger": trigger,
            "action": action,
            "reason": reason,
            "changes": changes,
            "recommended_commitment_updates": recommended_commitment_updates,
        }

    @classmethod
    def create_proposal(cls, *, session: GIESession, signals: list[dict]) -> GIEAdaptationProposal:
        payload = cls.generate_proposal_payload(session=session, signals=signals)
        return GIEAdaptationProposal.objects.create(
            session=session,
            trigger=payload["trigger"],
            action=payload["action"],
            reason=payload["reason"],
            changes=payload["changes"],
            recommended_commitment_updates=payload["recommended_commitment_updates"],
        )

    @staticmethod
    def _build_reduce_scope_changes(*, session: GIESession) -> list[dict]:
        slot_states = {state.slot_key: state for state in session.slot_states.all()}
        weekly_days_state = slot_states.get("weekly_availability_days")
        before_days = (
            int(weekly_days_state.value)
            if weekly_days_state and weekly_days_state.value is not None
            else 4
        )
        after_days = max(1, before_days - 1)
        return [
            {"target": "weekly_availability_days", "before": before_days, "after": after_days},
            {"target": "task_load_factor", "before": "1.0", "after": "0.8"},
        ]

    @staticmethod
    def _build_timeline_changes(*, session: GIESession) -> list[dict]:
        slot_states = {state.slot_key: state for state in session.slot_states.all()}
        timeline_state = slot_states.get("timeline_target_date")
        before_date = None
        if timeline_state and timeline_state.value:
            before_date = str(timeline_state.value)
        if before_date:
            try:
                parsed = timezone.datetime.strptime(before_date, "%Y-%m-%d").date()
                after_date = (parsed + timedelta(days=30)).isoformat()
            except ValueError:
                after_date = (timezone.localdate() + timedelta(days=120)).isoformat()
        else:
            after_date = (timezone.localdate() + timedelta(days=120)).isoformat()
        return [
            {"target": "timeline_target_date", "before": before_date, "after": after_date},
        ]
