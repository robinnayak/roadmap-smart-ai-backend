from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from gie.models import GIEPlanSnapshot, GIESession, GIESlotDefinition, GIESlotState, GIETurn
from gie.serializers import (
    GIEAutofillRequestSerializer,
    GIEAdaptationProposalSerializer,
    GIEAdaptationRequestSerializer,
    GIEFinalizeRequestSerializer,
    GIEGoalStartRequestSerializer,
    GIEPlanSnapshotSerializer,
    GIESessionSerializer,
    GIESlotDefinitionSerializer,
    GIESlotStateSerializer,
    GIETurnSerializer,
    GIETurnSubmitRequestSerializer,
)
from gie.services import (
    GIEAdaptationService,
    GIEDialogueManagerService,
    GIEDynamicSchemaService,
    GIEIntakeUnderstandingService,
    GIEObservabilityService,
    GIEPlanningService,
    GIERolloutPolicyService,
    GIETimelineFeasibilityService,
    GIETimelineValidationService,
    GIETurnPipelineService,
    GIEUnifiedContextService,
)
from gie.services.timeline_feasibility import TIMELINE_FEASIBILITY_SLOT_KEY
from gie.services.timeline_validation import (
    TIMELINE_REFRAME_ANALYSIS_KEY,
    TIMELINE_REFRAME_DECISION_KEY,
)


def error_payload(*, error: str, code: str, details: dict, status_code: int) -> Response:
    return Response(
        {
            "error": error,
            "code": code,
            "details": details,
            "status": status_code,
        },
        status=status_code,
    )


def rollout_policy_payload(*, code: str, message: str) -> Response:
    return error_payload(
        error="service_unavailable",
        code=code,
        details={
            "service": [message],
            "recoverable": ["true"],
        },
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


def get_rollout_policy_block(*, session: GIESession | None = None) -> Response | None:
    policy = GIERolloutPolicyService.current_gate()
    if not policy:
        return None
    code, message = policy
    GIEObservabilityService.record_policy_block(session=session, code=code)
    return rollout_policy_payload(code=code, message=message)


def merge_unique_slot_updates(existing: list[GIESlotState], incoming: list[GIESlotState]) -> list[GIESlotState]:
    updates_by_key = {slot.slot_key: slot for slot in existing}
    for slot in incoming:
        updates_by_key[slot.slot_key] = slot
    return sorted(updates_by_key.values(), key=lambda item: item.slot_key)


class GIESessionScopedAPIView(APIView):
    permission_classes = [IsAuthenticated]
    renderer_classes = [JSONRenderer]

    def get_session(self, request, session_id):
        try:
            return GIESession.objects.get(id=session_id, user=request.user)
        except GIESession.DoesNotExist:
            return None


class GIEGoalStartAPIView(APIView):
    permission_classes = [IsAuthenticated]
    renderer_classes = [JSONRenderer]

    def post(self, request):
        rollout_block = get_rollout_policy_block()
        if rollout_block:
            return rollout_block

        request_serializer = GIEGoalStartRequestSerializer(data=request.data)
        if not request_serializer.is_valid():
            return error_payload(
                error="validation_error",
                code="invalid_start_payload",
                details=request_serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        goal_text = request_serializer.validated_data["goal_text"]
        intake_analysis = GIEIntakeUnderstandingService.analyze_goal_text(goal_text)
        schema = GIEDynamicSchemaService.generate_schema(goal_text=goal_text, intake_analysis=intake_analysis)
        dialogue_state = GIEDialogueManagerService.build_initial_state(
            schema=schema,
            intake_analysis={**intake_analysis, "goal_text": goal_text},
        )

        completeness = dialogue_state["completeness"]
        next_prompt = dialogue_state["next_prompt"]
        session_status = (
            GIESession.STATUS_READY_TO_FINALIZE
            if completeness["filled_required_slot_count"] == completeness["required_slot_count"]
            else GIESession.STATUS_ACTIVE
        )
        session_phase = (
            GIESession.PHASE_REVIEW
            if session_status == GIESession.STATUS_READY_TO_FINALIZE
            else GIESession.PHASE_QUESTION_LOOP
        )

        with transaction.atomic():
            session = GIESession.objects.create(
                user=request.user,
                goal_text=goal_text,
                goal_domain=intake_analysis["goal_domain"]["value"],
                status=session_status,
                phase=session_phase,
                current_question=next_prompt["question"] if next_prompt else None,
                required_slot_count=completeness["required_slot_count"],
                filled_required_slot_count=completeness["filled_required_slot_count"],
                completeness_percent=completeness["completeness_percent"],
            )

            GIESlotDefinition.objects.bulk_create(
                [
                    GIESlotDefinition(
                        session=session,
                        key=slot["key"],
                        label=slot["label"],
                        description=slot["description"],
                        required=slot["required"],
                        data_type=slot["data_type"],
                        enum_values=slot["enum_values"],
                        validation=slot["validation"],
                    )
                    for slot in schema["required_slots"] + schema["optional_slots"]
                ]
            )

            GIESlotState.objects.bulk_create(
                [
                    GIESlotState(
                        session=session,
                        slot_key=state["slot_key"],
                        required=state["required"],
                        status=state["status"],
                        value=state["value"],
                        source=state["source"],
                        confidence=state["confidence"],
                        last_updated_turn_index=state["last_updated_turn_index"],
                        missing_reason=state["missing_reason"],
                    )
                    for state in dialogue_state["slot_state"]
                ]
            )

            if next_prompt:
                GIETurn.objects.create(
                    session=session,
                    turn_index=1,
                    role=GIETurn.ROLE_ASSISTANT,
                    kind=GIETurn.KIND_FOLLOWUP_QUESTION,
                    content=next_prompt["question"],
                    applied=False,
                )

        required_qs = GIESlotDefinition.objects.filter(session=session, required=True).order_by("key")
        optional_qs = GIESlotDefinition.objects.filter(session=session, required=False).order_by("key")
        slot_state_qs = GIESlotState.objects.filter(session=session).order_by("slot_key")
        GIEObservabilityService.record_session_started(session=session, completeness=completeness)

        return Response(
            {
                "session": GIESessionSerializer(session).data,
                "schema": {
                    "required_slots": GIESlotDefinitionSerializer(required_qs, many=True).data,
                    "optional_slots": GIESlotDefinitionSerializer(optional_qs, many=True).data,
                },
                "slot_state": GIESlotStateSerializer(slot_state_qs, many=True).data,
                "next_prompt": next_prompt,
            },
            status=status.HTTP_201_CREATED,
        )


class GIEGoalTurnAPIView(GIESessionScopedAPIView):
    @staticmethod
    def _get_latest_health_profile(*, user):
        try:
            from routine.health_profile_selector import get_effective_profile
        except Exception:
            return None
        return get_effective_profile(user=user)

    @classmethod
    def _sync_timeline_reframe_states(cls, *, session: GIESession, state_map: dict[str, GIESlotState], turn_index: int | None):
        required_definitions = list(session.slot_definitions.filter(required=True).order_by("key"))
        pending_required_prompt = GIETurnPipelineService.select_next_prompt(
            required_definitions,
            state_map,
            goal_text=session.goal_text,
        )

        # Only evaluate timeline realism once required slots are complete.
        if pending_required_prompt:
            analysis_state = state_map.get(TIMELINE_REFRAME_ANALYSIS_KEY)
            decision_state = state_map.get(TIMELINE_REFRAME_DECISION_KEY)
            updates = []
            if analysis_state and analysis_state.status != GIESlotState.STATUS_MISSING:
                analysis_state.status = GIESlotState.STATUS_MISSING
                analysis_state.value = None
                analysis_state.source = None
                analysis_state.confidence = None
                analysis_state.last_updated_turn_index = turn_index
                analysis_state.missing_reason = "required_slots_pending"
                analysis_state.save(
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
                updates.append(analysis_state)
            if decision_state and decision_state.status != GIESlotState.STATUS_MISSING:
                decision_state.status = GIESlotState.STATUS_MISSING
                decision_state.value = None
                decision_state.source = None
                decision_state.confidence = None
                decision_state.last_updated_turn_index = turn_index
                decision_state.missing_reason = "timeline_check_not_ready"
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
            return updates

        health_profile = cls._get_latest_health_profile(user=session.user)
        result = GIETimelineValidationService.evaluate(
            session=session,
            slot_states_by_key=state_map,
            health_profile=health_profile,
        )
        if not result:
            return []

        analysis_defaults = {
            "required": False,
            "status": GIESlotState.STATUS_LOCKED,
            "value": {
                "verdict": result.verdict,
                "achievable_sub_goal": result.achievable_sub_goal,
                "projected_full_goal_completion_date": result.projected_full_goal_completion_date,
                "impact_percent": result.impact_percent,
                "stated_timeline_days": result.stated_timeline_days,
                "estimated_timeline_days": result.estimated_timeline_days,
            },
            "source": GIESlotState.SOURCE_INFERENCE,
            "confidence": 0.9,
            "last_updated_turn_index": turn_index,
            "missing_reason": None,
        }
        analysis_state, _ = GIESlotState.objects.update_or_create(
            session=session,
            slot_key=TIMELINE_REFRAME_ANALYSIS_KEY,
            defaults=analysis_defaults,
        )

        decision_defaults = {
            "required": False,
            "status": GIESlotState.STATUS_MISSING,
            "value": None,
            "source": None,
            "confidence": None,
            "last_updated_turn_index": turn_index,
            "missing_reason": "timeline_reframe_pending" if result.needs_reframe else None,
        }
        existing_decision = state_map.get(TIMELINE_REFRAME_DECISION_KEY)
        if result.needs_reframe:
            if existing_decision and isinstance(existing_decision.value, dict):
                decision_value = existing_decision.value.get("decision")
                if decision_value in {"accept_reframed_plan", "adjust_manually"}:
                    decision_defaults["status"] = GIESlotState.STATUS_LOCKED
                    decision_defaults["value"] = existing_decision.value
                    decision_defaults["source"] = existing_decision.source or GIESlotState.SOURCE_TURN_ANSWER
                    decision_defaults["confidence"] = existing_decision.confidence or 1.0
                    decision_defaults["missing_reason"] = None
        else:
            decision_defaults.update(
                {
                    "status": GIESlotState.STATUS_LOCKED,
                    "value": {"decision": "timeline_realistic"},
                    "source": GIESlotState.SOURCE_INFERENCE,
                    "confidence": 1.0,
                    "missing_reason": None,
                }
            )

        decision_state, _ = GIESlotState.objects.update_or_create(
            session=session,
            slot_key=TIMELINE_REFRAME_DECISION_KEY,
            defaults=decision_defaults,
        )
        return [analysis_state, decision_state]

    @classmethod
    def _sync_timeline_feasibility_state(cls, *, session: GIESession, turn_index: int | None):
        slot_states = list(session.slot_states.all().order_by("slot_key"))
        required_definitions = list(session.slot_definitions.filter(required=True).order_by("key"))
        slot_map = {state.slot_key: state for state in slot_states}
        pending_required_prompt = GIETurnPipelineService.select_next_prompt(
            required_definitions,
            slot_map,
            goal_text=session.goal_text,
        )
        if pending_required_prompt:
            feasibility_state, _ = GIESlotState.objects.update_or_create(
                session=session,
                slot_key=TIMELINE_FEASIBILITY_SLOT_KEY,
                defaults={
                    "required": False,
                    "status": GIESlotState.STATUS_MISSING,
                    "value": None,
                    "source": None,
                    "confidence": None,
                    "last_updated_turn_index": turn_index,
                    "missing_reason": "required_slots_pending",
                },
            )
            return [feasibility_state]

        unified_context = GIEUnifiedContextService.build(session=session, slot_states=slot_states)
        feasibility_payload = GIETimelineFeasibilityService.evaluate(
            session=session,
            slot_states=slot_states,
            unified_context=unified_context,
        )
        feasibility_state, _ = GIESlotState.objects.update_or_create(
            session=session,
            slot_key=TIMELINE_FEASIBILITY_SLOT_KEY,
            defaults={
                "required": False,
                "status": GIESlotState.STATUS_LOCKED,
                "value": feasibility_payload,
                "source": GIESlotState.SOURCE_INFERENCE,
                "confidence": 0.95,
                "last_updated_turn_index": turn_index,
                "missing_reason": None,
            },
        )
        return [feasibility_state]

    @staticmethod
    def _is_timeline_reframe_unresolved(state_map: dict[str, GIESlotState]) -> bool:
        analysis = state_map.get(TIMELINE_REFRAME_ANALYSIS_KEY)
        decision = state_map.get(TIMELINE_REFRAME_DECISION_KEY)
        analysis_value = analysis.value if analysis else None
        if not isinstance(analysis_value, dict) or analysis_value.get("verdict") != "unrealistic":
            return False
        decision_value = decision.value if decision else None
        if not isinstance(decision_value, dict):
            return True
        return decision_value.get("decision") not in {"accept_reframed_plan", "adjust_manually"}

    def post(self, request, session_id):
        session = self.get_session(request, session_id)
        if not session:
            return error_payload(
                error="not_found",
                code="session_not_found",
                details={"session_id": ["Session does not exist for this user."]},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        rollout_block = get_rollout_policy_block(session=session)
        if rollout_block:
            return rollout_block

        request_serializer = GIETurnSubmitRequestSerializer(data=request.data)
        if not request_serializer.is_valid():
            return error_payload(
                error="validation_error",
                code="invalid_turn_payload",
                details=request_serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        client_turn_id = request_serializer.validated_data["client_turn_id"]
        answer = request_serializer.validated_data["answer"]
        existing_turn = GIETurn.objects.filter(
            session=session,
            role=GIETurn.ROLE_USER,
            client_turn_id=client_turn_id,
        ).first()
        if existing_turn:
            return self._build_turn_response(session=session, turn=existing_turn, replay=True)
        if session.status != GIESession.STATUS_ACTIVE:
            return error_payload(
                error="conflict",
                code="session_not_active",
                details={"session_status": ["Cannot accept turns for finalized session."]},
                status_code=status.HTTP_409_CONFLICT,
            )

        with transaction.atomic():
            session_locked = GIESession.objects.select_for_update().get(pk=session.pk)
            max_turn_index = session_locked.turns.order_by("-turn_index").values_list("turn_index", flat=True).first() or 0
            next_turn_index = max_turn_index + 1
            user_turn = GIETurn.objects.create(
                session=session_locked,
                turn_index=next_turn_index,
                role=GIETurn.ROLE_USER,
                kind=GIETurn.KIND_SLOT_ANSWER,
                content=answer,
                client_turn_id=client_turn_id,
                applied=False,
            )

            required_definitions = list(session_locked.slot_definitions.filter(required=True).order_by("key"))
            slot_states_by_key = {state.slot_key: state for state in session_locked.slot_states.all().order_by("slot_key")}
            next_prompt = GIETurnPipelineService.select_next_prompt_with_timeline_reframe(
                required_definitions,
                slot_states_by_key,
                goal_text=session_locked.goal_text,
            )
            target_slot_key = next_prompt["target_slot_key"] if next_prompt else None
            if target_slot_key == TIMELINE_REFRAME_DECISION_KEY:
                slot_updates, applied = GIETurnPipelineService.apply_timeline_reframe_decision_answer(
                    answer=answer,
                    timeline_state=slot_states_by_key.get("timeline_target_date"),
                    decision_state=slot_states_by_key.get(TIMELINE_REFRAME_DECISION_KEY),
                    turn_index=next_turn_index,
                )
            else:
                target_slot_definition = (
                    session_locked.slot_definitions.filter(key=target_slot_key).first() if target_slot_key else None
                )
                target_slot_state = slot_states_by_key.get(target_slot_key) if target_slot_key else None
                slot_updates, applied = GIETurnPipelineService.apply_answer_to_target_slot(
                    answer=answer,
                    target_slot_definition=target_slot_definition,
                    target_slot_state=target_slot_state,
                    turn_index=next_turn_index,
                )
            if applied:
                user_turn.applied = True
                user_turn.save(update_fields=["applied"])

            refreshed_state_map = {state.slot_key: state for state in session_locked.slot_states.all().order_by("slot_key")}
            timeline_updates = self._sync_timeline_reframe_states(
                session=session_locked,
                state_map=refreshed_state_map,
                turn_index=next_turn_index,
            )
            if timeline_updates:
                slot_updates = merge_unique_slot_updates(slot_updates, timeline_updates)
            feasibility_updates = self._sync_timeline_feasibility_state(
                session=session_locked,
                turn_index=next_turn_index,
            )
            if feasibility_updates:
                slot_updates = merge_unique_slot_updates(slot_updates, feasibility_updates)

            refreshed_states = list(session_locked.slot_states.all().order_by("slot_key"))
            completeness = GIETurnPipelineService.compute_completeness_from_states(refreshed_states)
            refreshed_state_map = {state.slot_key: state for state in refreshed_states}
            followup_prompt = GIETurnPipelineService.select_next_prompt_with_timeline_reframe(
                required_definitions,
                refreshed_state_map,
                goal_text=session_locked.goal_text,
            )
            timeline_blocking = self._is_timeline_reframe_unresolved(refreshed_state_map)
            session_status = GIESession.STATUS_READY_TO_FINALIZE
            if (
                completeness["filled_required_slot_count"] != completeness["required_slot_count"]
                or timeline_blocking
            ):
                session_status = GIESession.STATUS_ACTIVE
            session_phase = GIESession.PHASE_REVIEW if session_status == GIESession.STATUS_READY_TO_FINALIZE else GIESession.PHASE_QUESTION_LOOP
            session_locked.status = session_status
            session_locked.phase = session_phase
            session_locked.current_question = followup_prompt["question"] if followup_prompt else None
            session_locked.required_slot_count = completeness["required_slot_count"]
            session_locked.filled_required_slot_count = completeness["filled_required_slot_count"]
            session_locked.completeness_percent = completeness["completeness_percent"]
            session_locked.save(
                update_fields=[
                    "status",
                    "phase",
                    "current_question",
                    "required_slot_count",
                    "filled_required_slot_count",
                    "completeness_percent",
                    "updated_at",
                ]
            )

            if followup_prompt and session_status == GIESession.STATUS_ACTIVE:
                assistant_turn_index = (session_locked.turns.order_by("-turn_index").values_list("turn_index", flat=True).first() or 0) + 1
                GIETurn.objects.create(
                    session=session_locked,
                    turn_index=assistant_turn_index,
                    role=GIETurn.ROLE_ASSISTANT,
                    kind=GIETurn.KIND_FOLLOWUP_QUESTION,
                    content=followup_prompt["question"],
                    applied=False,
                )
            elif session_status == GIESession.STATUS_READY_TO_FINALIZE:
                _, habit_suggestions_state = GIEPlanningService.ensure_ranked_habit_suggestions(session=session_locked)
                autofill_state = GIEPlanningService.ensure_goal_details_autofill_state(
                    session=session_locked,
                    slot_states=refreshed_states,
                )
                slot_updates = merge_unique_slot_updates(slot_updates, [habit_suggestions_state, autofill_state])
            GIEObservabilityService.record_turn_processed(session=session_locked, completeness=completeness)

        return Response(
            {
                "session_id": str(session_id),
                "turn": GIETurnSerializer(user_turn).data,
                "slot_updates": GIESlotStateSerializer(slot_updates, many=True).data,
                "completeness": completeness,
                "next_prompt": followup_prompt,
                "session_status": session_status,
            },
            status=status.HTTP_200_OK,
        )

    def _build_turn_response(self, *, session: GIESession, turn: GIETurn, replay: bool) -> Response:
        slot_updates = list(session.slot_states.filter(last_updated_turn_index=turn.turn_index).order_by("slot_key"))
        all_states = list(session.slot_states.all().order_by("slot_key"))
        completeness = GIETurnPipelineService.compute_completeness_from_states(all_states)
        required_definitions = list(session.slot_definitions.filter(required=True).order_by("key"))
        state_map = {state.slot_key: state for state in all_states}
        next_prompt = GIETurnPipelineService.select_next_prompt_with_timeline_reframe(
            required_definitions,
            state_map,
            goal_text=session.goal_text,
        )
        session_status = GIESession.STATUS_READY_TO_FINALIZE
        if completeness["filled_required_slot_count"] != completeness["required_slot_count"] or self._is_timeline_reframe_unresolved(state_map):
            session_status = GIESession.STATUS_ACTIVE
        if session_status == GIESession.STATUS_READY_TO_FINALIZE:
            _, habit_suggestions_state = GIEPlanningService.ensure_ranked_habit_suggestions(session=session)
            autofill_state = GIEPlanningService.ensure_goal_details_autofill_state(
                session=session,
                slot_states=all_states,
            )
            slot_updates = merge_unique_slot_updates(slot_updates, [habit_suggestions_state, autofill_state])
        _ = replay
        return Response(
            {
                "session_id": str(session.id),
                "turn": GIETurnSerializer(turn).data,
                "slot_updates": GIESlotStateSerializer(slot_updates, many=True).data,
                "completeness": completeness,
                "next_prompt": next_prompt,
                "session_status": session_status,
            },
            status=status.HTTP_200_OK,
        )


class GIEGoalStateAPIView(GIESessionScopedAPIView):
    def get(self, request, session_id):
        session = self.get_session(request, session_id)
        if not session:
            return error_payload(
                error="not_found",
                code="session_not_found",
                details={"session_id": ["Session does not exist for this user."]},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        rollout_block = get_rollout_policy_block(session=session)
        if rollout_block:
            return rollout_block

        if session.status in (GIESession.STATUS_READY_TO_FINALIZE, GIESession.STATUS_FINALIZED):
            GIEPlanningService.ensure_ranked_habit_suggestions(session=session)
            GIEPlanningService.ensure_goal_details_autofill_state(session=session)

        required_qs = GIESlotDefinition.objects.filter(session=session, required=True).order_by("key")
        optional_qs = GIESlotDefinition.objects.filter(session=session, required=False).order_by("key")
        slot_state_qs = list(GIESlotState.objects.filter(session=session).order_by("slot_key"))
        completeness = GIETurnPipelineService.compute_completeness_from_states(slot_state_qs)
        GIEObservabilityService.record_state_read(session=session, completeness=completeness)

        return Response(
            {
                "session": GIESessionSerializer(session).data,
                "schema": {
                    "required_slots": GIESlotDefinitionSerializer(required_qs, many=True).data,
                    "optional_slots": GIESlotDefinitionSerializer(optional_qs, many=True).data,
                },
                "slot_state": GIESlotStateSerializer(slot_state_qs, many=True).data,
                "completeness": completeness,
            },
            status=status.HTTP_200_OK,
        )


class GIEGoalFinalizeAPIView(GIESessionScopedAPIView):
    def post(self, request, session_id):
        session = self.get_session(request, session_id)
        if not session:
            return error_payload(
                error="not_found",
                code="session_not_found",
                details={"session_id": ["Session does not exist for this user."]},
                status_code=status.HTTP_404_NOT_FOUND,
            )
        rollout_block = get_rollout_policy_block(session=session)
        if rollout_block:
            return rollout_block

        if session.status not in (GIESession.STATUS_READY_TO_FINALIZE, GIESession.STATUS_FINALIZED):
            return error_payload(
                error="conflict",
                code="session_not_ready_to_finalize",
                details={"session_status": ["Session must be ready_to_finalize before finalize."]},
                status_code=status.HTTP_409_CONFLICT,
            )
        state_map = {state.slot_key: state for state in session.slot_states.all().order_by("slot_key")}
        if GIEGoalTurnAPIView._is_timeline_reframe_unresolved(state_map):
            return error_payload(
                error="conflict",
                code="timeline_reframe_unresolved",
                details={"session_status": ["Timeline reframe decision is required before finalize."]},
                status_code=status.HTTP_409_CONFLICT,
            )

        request_serializer = GIEFinalizeRequestSerializer(data=request.data)
        if not request_serializer.is_valid():
            return error_payload(
                error="validation_error",
                code="invalid_finalize_payload",
                details=request_serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        GIEObservabilityService.record_finalize_attempt(session=session)
        snapshot, commitments, rie_signal, bridge_result, contract_error, feasibility = GIEPlanningService.finalize_session(
            session=session,
            commitments_input=request_serializer.validated_data.get("commitments", []),
            habit_confirmations_input=request_serializer.validated_data.get("habit_confirmations", []),
            form_goal_context=request_serializer.validated_data.get("goal_context", {}),
        )
        if contract_error:
            if contract_error["code"] == "finalize_bridge_failed":
                GIEObservabilityService.record_finalize_failure(
                    session=session,
                    error_code=contract_error["code"],
                )
            return error_payload(
                error=contract_error["error"],
                code=contract_error["code"],
                details=contract_error["details"],
                status_code=contract_error["status"],
            )

        finalized_session = GIESession.objects.get(pk=session.pk)
        GIEObservabilityService.record_finalize_success(session=finalized_session)
        return Response(
            {
                "session_id": str(finalized_session.id),
                "session_status": finalized_session.status,
                "plan_snapshot": GIEPlanSnapshotSerializer(snapshot).data,
                "commitments": commitments,
                "rie_signal": rie_signal,
                "goal": (bridge_result.payload or {}).get("goal") if bridge_result else None,
                "goal_generation": (bridge_result.payload or {}).get("job") if bridge_result else None,
                "feasibility": feasibility,
            },
            status=status.HTTP_200_OK,
        )


class GIEGoalPlanAPIView(GIESessionScopedAPIView):
    def get(self, request, session_id):
        session = self.get_session(request, session_id)
        if not session:
            return error_payload(
                error="not_found",
                code="session_not_found",
                details={"session_id": ["Session does not exist for this user."]},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        rollout_block = get_rollout_policy_block(session=session)
        if rollout_block:
            return rollout_block

        snapshot = (
            GIEPlanSnapshot.objects.filter(session=session)
            .order_by("-created_at")
            .first()
        )
        if not snapshot:
            return error_payload(
                error="not_found",
                code="plan_snapshot_not_found",
                details={"session_id": ["No plan snapshot found for this session."]},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            {
                "session_id": str(session.id),
                "plan_snapshot": GIEPlanSnapshotSerializer(snapshot).data,
            },
            status=status.HTTP_200_OK,
        )


class GIEGoalAutofillAPIView(GIESessionScopedAPIView):
    def post(self, request, session_id):
        session = self.get_session(request, session_id)
        if not session:
            return error_payload(
                error="not_found",
                code="session_not_found",
                details={"session_id": ["Session does not exist for this user."]},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        rollout_block = get_rollout_policy_block(session=session)
        if rollout_block:
            return rollout_block

        request_serializer = GIEAutofillRequestSerializer(data=request.data)
        if not request_serializer.is_valid():
            return error_payload(
                error="validation_error",
                code="invalid_autofill_payload",
                details=request_serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        slot_states = list(session.slot_states.all().order_by("slot_key"))
        autofill_state = GIEPlanningService.ensure_goal_details_autofill_state(
            session=session,
            slot_states=slot_states,
            form_goal_context=request_serializer.validated_data.get("goal_context", {}),
            refine_language=bool(request_serializer.validated_data.get("refine_language", False)),
        )
        return Response(
            {
                "session_id": str(session.id),
                "autofill": autofill_state.value or {},
            },
            status=status.HTTP_200_OK,
        )


class GIEGoalAdaptAPIView(GIESessionScopedAPIView):
    def post(self, request, session_id):
        session = self.get_session(request, session_id)
        if not session:
            return error_payload(
                error="not_found",
                code="session_not_found",
                details={"session_id": ["Session does not exist for this user."]},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        rollout_block = get_rollout_policy_block(session=session)
        if rollout_block:
            return rollout_block

        request_serializer = GIEAdaptationRequestSerializer(data=request.data)
        if not request_serializer.is_valid():
            return error_payload(
                error="validation_error",
                code="invalid_adaptation_signal_payload",
                details=request_serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        proposal = GIEAdaptationService.create_proposal(
            session=session,
            signals=request_serializer.validated_data["signals"],
        )
        GIEObservabilityService.record_adaptation_generated(session=session)
        return Response(
            {
                "session_id": str(session.id),
                "proposal": GIEAdaptationProposalSerializer(proposal).data,
            },
            status=status.HTTP_200_OK,
        )
