import re
from datetime import timedelta

from django.utils import timezone

from gie.models import GIESession, GIESlotDefinition, GIESlotState
from gie.services.dialogue_manager import GIEDialogueManagerService
from gie.services.timeline_validation import (
    DECISION_ACCEPT,
    DECISION_ADJUST,
    TIMELINE_REFRAME_ANALYSIS_KEY,
    TIMELINE_REFRAME_DECISION_KEY,
)


class GIETurnPipelineService:
    @staticmethod
    def compute_completeness_from_states(slot_states: list[GIESlotState]) -> dict:
        required_states = [state for state in slot_states if state.required]
        required_slot_count = len(required_states)
        filled_required_slot_count = len(
            [state for state in required_states if state.status in (GIESlotState.STATUS_FILLED, GIESlotState.STATUS_LOCKED)]
        )
        missing_required_slot_keys = [
            state.slot_key
            for state in required_states
            if state.status not in (GIESlotState.STATUS_FILLED, GIESlotState.STATUS_LOCKED)
        ]
        completeness_percent = (
            round((filled_required_slot_count / required_slot_count) * 100, 2) if required_slot_count else 100.0
        )
        return {
            "required_slot_count": required_slot_count,
            "filled_required_slot_count": filled_required_slot_count,
            "completeness_percent": completeness_percent,
            "missing_required_slot_keys": missing_required_slot_keys,
        }

    @staticmethod
    def select_next_prompt(slot_definitions: list[GIESlotDefinition], slot_states: dict[str, GIESlotState]) -> dict | None:
        for definition in slot_definitions:
            state = slot_states.get(definition.key)
            if not state:
                continue
            if state.status in (GIESlotState.STATUS_FILLED, GIESlotState.STATUS_LOCKED):
                continue
            question = GIEDialogueManagerService.SLOT_QUESTION_MAP.get(definition.key) or (
                f"What is your {definition.label.lower()}?"
            )
            return {"question": question, "target_slot_key": definition.key}
        return None

    @staticmethod
    def select_next_prompt_with_timeline_reframe(
        slot_definitions: list[GIESlotDefinition],
        slot_states: dict[str, GIESlotState],
    ) -> dict | None:
        missing_required_prompt = GIETurnPipelineService.select_next_prompt(slot_definitions, slot_states)
        if missing_required_prompt:
            return missing_required_prompt

        analysis_state = slot_states.get(TIMELINE_REFRAME_ANALYSIS_KEY)
        decision_state = slot_states.get(TIMELINE_REFRAME_DECISION_KEY)
        analysis_value = analysis_state.value if analysis_state else None
        needs_reframe = bool(isinstance(analysis_value, dict) and analysis_value.get("verdict") == "unrealistic")
        decision_value = decision_state.value if decision_state else None
        has_decision = bool(isinstance(decision_value, dict) and decision_value.get("decision") in {DECISION_ACCEPT, DECISION_ADJUST})

        if needs_reframe and not has_decision:
            return {
                "question": "This timeline looks unrealistic. Accept the reframed plan or adjust your target date.",
                "target_slot_key": TIMELINE_REFRAME_DECISION_KEY,
            }
        return None

    @classmethod
    def apply_answer_to_target_slot(
        cls,
        *,
        answer: str,
        target_slot_definition: GIESlotDefinition | None,
        target_slot_state: GIESlotState | None,
        turn_index: int,
    ) -> tuple[list[GIESlotState], bool]:
        if target_slot_definition is None or target_slot_state is None:
            return [], False

        extracted_value, confidence = cls._extract_value(
            answer=answer,
            data_type=target_slot_definition.data_type,
            enum_values=target_slot_definition.enum_values,
            validation=target_slot_definition.validation or {},
        )
        if extracted_value is None:
            target_slot_state.status = GIESlotState.STATUS_PARTIAL
            target_slot_state.missing_reason = "unable_to_extract_value"
            target_slot_state.last_updated_turn_index = turn_index
            target_slot_state.save(update_fields=["status", "missing_reason", "last_updated_turn_index", "updated_at"])
            return [], False

        target_slot_state.status = GIESlotState.STATUS_FILLED
        target_slot_state.value = extracted_value
        target_slot_state.source = GIESlotState.SOURCE_TURN_ANSWER
        target_slot_state.confidence = confidence
        target_slot_state.last_updated_turn_index = turn_index
        target_slot_state.missing_reason = None
        target_slot_state.save(
            update_fields=[
                "status",
                "value",
                "source",
                "confidence",
                "last_updated_turn_index",
                "missing_reason",
                "updated_at",
            ]
        )
        return [target_slot_state], True

    @classmethod
    def apply_timeline_reframe_decision_answer(
        cls,
        *,
        answer: str,
        timeline_state: GIESlotState | None,
        decision_state: GIESlotState | None,
        turn_index: int,
    ) -> tuple[list[GIESlotState], bool]:
        if decision_state is None:
            return [], False

        normalized = (answer or "").strip().lower()
        updates: list[GIESlotState] = []

        if normalized in {"accept", "accept_reframed_plan", "accept reframed plan", "accept reframe"}:
            decision_state.status = GIESlotState.STATUS_LOCKED
            decision_state.value = {"decision": DECISION_ACCEPT}
            decision_state.source = GIESlotState.SOURCE_TURN_ANSWER
            decision_state.confidence = 1.0
            decision_state.last_updated_turn_index = turn_index
            decision_state.missing_reason = None
            decision_state.save(
                update_fields=[
                    "status",
                    "value",
                    "source",
                    "confidence",
                    "last_updated_turn_index",
                    "missing_reason",
                    "updated_at",
                ]
            )
            updates.append(decision_state)
            return updates, True

        adjusted_date = cls._extract_adjusted_timeline_target(answer)
        if adjusted_date and timeline_state is not None:
            timeline_state.status = GIESlotState.STATUS_FILLED
            timeline_state.value = adjusted_date
            timeline_state.source = GIESlotState.SOURCE_TURN_ANSWER
            timeline_state.confidence = 0.92
            timeline_state.last_updated_turn_index = turn_index
            timeline_state.missing_reason = None
            timeline_state.save(
                update_fields=[
                    "status",
                    "value",
                    "source",
                    "confidence",
                    "last_updated_turn_index",
                    "missing_reason",
                    "updated_at",
                ]
            )
            updates.append(timeline_state)

            decision_state.status = GIESlotState.STATUS_LOCKED
            decision_state.value = {
                "decision": DECISION_ADJUST,
                "adjusted_target_date": adjusted_date,
            }
            decision_state.source = GIESlotState.SOURCE_TURN_ANSWER
            decision_state.confidence = 1.0
            decision_state.last_updated_turn_index = turn_index
            decision_state.missing_reason = None
            decision_state.save(
                update_fields=[
                    "status",
                    "value",
                    "source",
                    "confidence",
                    "last_updated_turn_index",
                    "missing_reason",
                    "updated_at",
                ]
            )
            updates.append(decision_state)
            return updates, True

        decision_state.status = GIESlotState.STATUS_PARTIAL
        decision_state.value = None
        decision_state.source = GIESlotState.SOURCE_TURN_ANSWER
        decision_state.confidence = 0.2
        decision_state.last_updated_turn_index = turn_index
        decision_state.missing_reason = "invalid_timeline_reframe_decision"
        decision_state.save(
            update_fields=[
                "status",
                "value",
                "source",
                "confidence",
                "last_updated_turn_index",
                "missing_reason",
                "updated_at",
            ]
        )
        return [decision_state], False

    @classmethod
    def _extract_value(
        cls,
        *,
        answer: str,
        data_type: str,
        enum_values,
        validation: dict,
    ) -> tuple[object | None, float | None]:
        normalized = (answer or "").strip()
        if not normalized:
            return None, None

        if data_type == GIESlotDefinition.TYPE_STRING:
            min_length = int(validation.get("min_length", 0))
            if len(normalized) < min_length:
                return None, None
            return normalized, 0.88

        if data_type == GIESlotDefinition.TYPE_NUMBER:
            match = re.search(r"-?\d+(?:\.\d+)?", normalized)
            if not match:
                return None, None
            value = float(match.group(0))
            if not cls._passes_number_bounds(value, validation):
                return None, None
            return value, 0.9

        if data_type == GIESlotDefinition.TYPE_INTEGER:
            match = re.search(r"-?\d+", normalized)
            if not match:
                return None, None
            value = int(match.group(0))
            if not cls._passes_number_bounds(value, validation):
                return None, None
            return value, 0.9

        if data_type == GIESlotDefinition.TYPE_BOOLEAN:
            lowered = normalized.lower()
            if lowered in {"true", "yes", "y", "1"}:
                return True, 0.92
            if lowered in {"false", "no", "n", "0"}:
                return False, 0.92
            return None, None

        if data_type == GIESlotDefinition.TYPE_DATE:
            parsed = cls._parse_date(normalized)
            return (parsed, 0.86) if parsed else (None, None)

        if data_type == GIESlotDefinition.TYPE_ENUM:
            if not enum_values:
                return None, None
            lowered = normalized.lower()
            for enum_value in enum_values:
                if lowered == str(enum_value).lower():
                    return enum_value, 0.9
            return None, None

        if data_type == GIESlotDefinition.TYPE_LIST_STRING:
            values = [part.strip() for part in re.split(r",|;|\n", normalized) if part.strip()]
            if not values:
                return None, None
            return values, 0.84

        return None, None

    @staticmethod
    def _passes_number_bounds(value: float, validation: dict) -> bool:
        minimum = validation.get("minimum")
        maximum = validation.get("maximum")
        if minimum is not None and value < float(minimum):
            return False
        if maximum is not None and value > float(maximum):
            return False
        return True

    @staticmethod
    def _parse_date(value: str) -> str | None:
        trimmed = value.strip()
        for date_format in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y"):
            try:
                parsed_date = timezone.datetime.strptime(trimmed, date_format).date()
                return parsed_date.isoformat()
            except ValueError:
                continue

        horizon_match = re.search(r"(\d+)\s*(day|week|month|year)s?\b", trimmed.lower())
        if horizon_match:
            amount = int(horizon_match.group(1))
            unit = horizon_match.group(2)
            days_per_unit = {"day": 1, "week": 7, "month": 30, "year": 365}
            target_date = timezone.localdate() + timedelta(days=amount * days_per_unit[unit])
            return target_date.isoformat()
        return None

    @classmethod
    def _extract_adjusted_timeline_target(cls, answer: str) -> str | None:
        normalized = (answer or "").strip()
        if not normalized:
            return None
        lowered = normalized.lower()
        if lowered.startswith("adjust_timeline:"):
            candidate = normalized.split(":", 1)[1].strip()
            return cls._parse_date(candidate)
        return cls._parse_date(normalized)


def map_goal_domain_to_primary_category(goal_domain: str) -> str:
    if goal_domain in {GIESession.DOMAIN_CAREER, GIESession.DOMAIN_FINANCIAL, GIESession.DOMAIN_HEALTH}:
        return goal_domain
    return "personal"
