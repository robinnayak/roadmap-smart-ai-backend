from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
import json
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework.response import Response
from unittest.mock import patch

from gie.models import (
    GIEAdaptationProposal,
    GIEPlanSnapshot,
    GIESession,
    GIESessionAnalytics,
    GIESlotDefinition,
    GIESlotState,
    GIETurn,
)
from goal.models import Goal, GoalCommitmentRecord
from gie.services import (
    GIEHabitRankingService,
    GIEDialogueManagerService,
    GIEDynamicSchemaService,
    GIEIntakeUnderstandingService,
    GIEObservabilityService,
    GIETimelineFeasibilityService,
    GIETimelineValidationService,
)
from gie.services.timeline_validation import TIMELINE_REFRAME_ANALYSIS_KEY, TIMELINE_REFRAME_DECISION_KEY
from gie.services.planning import GIEFinalizeBridgeResult, GIEPlanningService
from goal.services.contract_template import GoalContractTemplateService


def full_goal_commitment_context(*, user=None, goal_data=None, accepted_commitments=None, include_snapshot=True, **overrides):
    signed_at = overrides.get("signed_at", timezone.now().isoformat())
    payload = {
        "commitment_confirmed": True,
        "commitment_intent": "I am committing to this goal.",
        "commitment_effort": "I will put in the required work consistently.",
        "commitment_responsibility": "I accept responsibility for the outcome.",
        "signed_name": "GIE Test User",
        "signed_at": signed_at,
    }
    payload.update(overrides)
    resolved_goal_data = {
        "title": "I want to improve my health in six months.",
        "description": "Improve my health steadily.",
        "primary_category": "fitness",
        "why_it_matters": ["health", "consistency"],
        "why_do_i_want_this": "I want to feel stronger and more consistent.",
        "specific_measurable_target": "Run stronger and stay consistent for six months.",
        "target_date": str(timezone.localdate() + timedelta(days=180)),
    }
    if goal_data:
        resolved_goal_data.update(goal_data)
    resolved_user = user or type(
        "UserStub",
        (),
        {"email": "gie-test@example.com", "get_full_name": lambda self: ""},
    )()
    if include_snapshot:
        payload["contract_snapshot"] = GoalContractTemplateService().render_snapshot(
            goal_data=resolved_goal_data,
            user=resolved_user,
            signed_name=payload["signed_name"],
            signed_at=payload["signed_at"],
            accepted_gie_commitments=accepted_commitments or [],
        )
    return payload


def populate_running_slot_profile(session: GIESession, *, timeline_days: int = 180) -> None:
    slot_defaults = {
        "current_fitness_baseline": "can run 2 km comfortably",
        "running_experience": "beginner",
        "weekly_training_days": 4,
        "daily_session_minutes": 45,
        "injury_constraints": "none",
        "equipment_and_location": "road running shoes and nearby track",
        "motivation_driver": "finish first race",
        "timeline_target_date": str(timezone.localdate() + timedelta(days=timeline_days)),
    }
    for slot_key, value in slot_defaults.items():
        GIESlotState.objects.update_or_create(
            session=session,
            slot_key=slot_key,
            defaults={
                "required": slot_key != "timeline_target_date",
                "status": GIESlotState.STATUS_FILLED,
                "value": value,
                "source": GIESlotState.SOURCE_TURN_ANSWER,
                "confidence": 1.0,
                "last_updated_turn_index": 1,
                "missing_reason": None,
            },
        )


def accepted_commitment_decisions() -> list[dict]:
    return [
        {"id": "c1", "decision": "accepted", "revision_note": None},
        {"id": "c2", "decision": "accepted", "revision_note": None},
    ]


class GIEModelConstraintTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            email='gie-models@test.com',
            password='Password@123',
        )
        self.session = GIESession.objects.create(
            user=self.user,
            goal_text='Build a consistent study routine in 90 days.',
            goal_domain=GIESession.DOMAIN_LEARNING,
            status=GIESession.STATUS_ACTIVE,
            phase=GIESession.PHASE_QUESTION_LOOP,
            required_slot_count=3,
            filled_required_slot_count=1,
            completeness_percent=33.3,
        )

    def test_turn_index_unique_per_session(self):
        GIETurn.objects.create(
            session=self.session,
            turn_index=1,
            role=GIETurn.ROLE_USER,
            kind=GIETurn.KIND_GOAL_STATEMENT,
            content='I want to study every weekday.',
        )
        with self.assertRaises(IntegrityError):
            GIETurn.objects.create(
                session=self.session,
                turn_index=1,
                role=GIETurn.ROLE_ASSISTANT,
                kind=GIETurn.KIND_FOLLOWUP_QUESTION,
                content='How many minutes can you commit daily?',
            )

    def test_client_turn_id_unique_when_present(self):
        GIETurn.objects.create(
            session=self.session,
            turn_index=1,
            role=GIETurn.ROLE_USER,
            kind=GIETurn.KIND_SLOT_ANSWER,
            content='I can do 45 minutes.',
            client_turn_id='turn-001',
        )
        with self.assertRaises(IntegrityError):
            GIETurn.objects.create(
                session=self.session,
                turn_index=2,
                role=GIETurn.ROLE_USER,
                kind=GIETurn.KIND_SLOT_ANSWER,
                content='Still 45 minutes.',
                client_turn_id='turn-001',
            )

    def test_slot_definition_unique_key_per_session(self):
        GIESlotDefinition.objects.create(
            session=self.session,
            key='timeline_target_date',
            label='Target Date',
            required=True,
            data_type=GIESlotDefinition.TYPE_DATE,
            validation={},
        )
        with self.assertRaises(IntegrityError):
            GIESlotDefinition.objects.create(
                session=self.session,
                key='timeline_target_date',
                label='Duplicate Target Date',
                required=True,
                data_type=GIESlotDefinition.TYPE_DATE,
                validation={},
            )

    def test_slot_state_unique_key_per_session(self):
        GIESlotState.objects.create(
            session=self.session,
            slot_key='weekly_availability_days',
            required=True,
            status=GIESlotState.STATUS_FILLED,
            value=4,
            source=GIESlotState.SOURCE_TURN_ANSWER,
            confidence=0.95,
            last_updated_turn_index=2,
        )
        with self.assertRaises(IntegrityError):
            GIESlotState.objects.create(
                session=self.session,
                slot_key='weekly_availability_days',
                required=True,
                status=GIESlotState.STATUS_PARTIAL,
                value=3,
            )


class GIEIntakeUnderstandingServiceTests(TestCase):
    def test_classifies_health_domain_from_running_goal(self):
        analysis = GIEIntakeUnderstandingService.analyze_goal_text(
            'I want to run my first half marathon in 6 months while balancing work.'
        )
        self.assertEqual(analysis['goal_domain']['value'], 'health')
        self.assertGreaterEqual(analysis['goal_domain']['confidence'], 0.45)
        self.assertIn('run', analysis['goal_domain']['matched_signals'])

    def test_classifies_financial_domain_from_savings_goal(self):
        analysis = GIEIntakeUnderstandingService.analyze_goal_text(
            'I want to save money and build an emergency fund in 12 months.'
        )
        self.assertEqual(analysis['goal_domain']['value'], 'financial')
        self.assertIn('save', analysis['goal_domain']['matched_signals'])

    def test_extracts_cadence_and_horizon_signals(self):
        analysis = GIEIntakeUnderstandingService.analyze_goal_text(
            'I can train 4 days per week and complete this in 6 months.'
        )
        self.assertEqual(
            analysis['nlu']['weekly_cadence'],
            {'raw': '4 days per week', 'value': 4, 'unit': 'times_per_week'},
        )
        self.assertEqual(
            analysis['nlu']['time_horizon'],
            {'raw': '6 months', 'value': 6, 'unit': 'months'},
        )

    def test_prefers_build_habit_intent_for_consistency_language(self):
        analysis = GIEIntakeUnderstandingService.analyze_goal_text(
            'I want a daily routine and to stay consistent 5 times a week.'
        )
        self.assertEqual(analysis['intent']['value'], 'build_habit')
        self.assertGreaterEqual(analysis['intent']['score_breakdown']['build_habit'], 1)

    def test_returns_deterministic_json_output(self):
        text = 'I want to launch my startup and get first paying customers in 3 months.'
        first = GIEIntakeUnderstandingService.analyze_goal_text(text)
        second = GIEIntakeUnderstandingService.analyze_goal_text(text)
        self.assertEqual(first, second)


class GIEDynamicSchemaServiceTests(TestCase):
    def test_returns_schema_with_required_and_optional_slots(self):
        analysis = {
            "goal_domain": {"value": "health"},
            "intent": {"value": "achieve_outcome"},
            "nlu": {},
        }
        schema = GIEDynamicSchemaService.generate_schema(
            goal_text="I want to run a half marathon.",
            intake_analysis=analysis,
        )

        self.assertIn("required_slots", schema)
        self.assertIn("optional_slots", schema)
        self.assertGreater(len(schema["required_slots"]), 0)
        self.assertGreater(len(schema["optional_slots"]), 0)

        sample_slot = schema["required_slots"][0]
        self.assertEqual(
            sorted(sample_slot.keys()),
            sorted(["key", "label", "description", "required", "data_type", "enum_values", "validation"]),
        )

    def test_enforces_governance_required_keys_and_counts(self):
        schema_by_domain = {
            "health": GIEDynamicSchemaService.generate_schema(
                goal_text="Run a half marathon this year.",
                intake_analysis={"goal_domain": {"value": "health"}},
            ),
            "financial": GIEDynamicSchemaService.generate_schema(
                goal_text="Save $10,000 by next year.",
                intake_analysis={"goal_domain": {"value": "financial"}},
            ),
            "learning": GIEDynamicSchemaService.generate_schema(
                goal_text="Learn guitar improvisation.",
                intake_analysis={"goal_domain": {"value": "learning"}},
            ),
            "career": GIEDynamicSchemaService.generate_schema(
                goal_text="Get promoted to staff engineer.",
                intake_analysis={"goal_domain": {"value": "career"}},
            ),
        }

        expected_required_by_domain = {
            "health": {
                "current_fitness_baseline",
                "running_experience",
                "weekly_training_days",
                "daily_session_minutes",
                "injury_constraints",
                "equipment_and_location",
                "motivation_driver",
            },
            "financial": {
                "savings_target",
                "target_date",
                "monthly_income",
                "monthly_fixed_expenses",
                "current_savings",
                "existing_debt",
                "savings_purpose",
            },
            "learning": {
                "current_skill_level",
                "has_required_equipment",
                "preferred_style_or_genre",
                "daily_practice_minutes",
                "goal_milestone_event",
                "learning_method",
            },
            "career": {
                "current_role",
                "target_role",
                "time_in_current_role",
                "target_timeline",
                "manager_feedback_on_gaps",
                "available_opportunities",
            },
        }

        for domain, schema in schema_by_domain.items():
            required_keys = {slot["key"] for slot in schema["required_slots"]}
            self.assertEqual(required_keys, expected_required_by_domain[domain])
            self.assertGreaterEqual(len(required_keys), 6)
            self.assertLessEqual(len(required_keys), 8)

    def test_running_schema_keeps_timeline_target_date_optional(self):
        schema = GIEDynamicSchemaService.generate_schema(
            goal_text="Run my first half marathon.",
            intake_analysis={"goal_domain": {"value": "health"}},
        )
        required_keys = {slot["key"] for slot in schema["required_slots"]}
        optional_keys = {slot["key"] for slot in schema["optional_slots"]}
        self.assertNotIn("timeline_target_date", required_keys)
        self.assertIn("timeline_target_date", optional_keys)

    def test_schema_generation_is_deterministic(self):
        analysis = {"goal_domain": {"value": "financial"}}
        first = GIEDynamicSchemaService.generate_schema("Save $10,000.", analysis)
        second = GIEDynamicSchemaService.generate_schema("Save $10,000.", analysis)
        self.assertEqual(first, second)


class GIEDialogueManagerServiceTests(TestCase):
    def test_build_initial_state_prefills_weekly_cadence_when_slot_exists(self):
        schema = GIEDynamicSchemaService.generate_schema(
            goal_text="I can train 4 days per week.",
            intake_analysis={"goal_domain": {"value": "health"}},
        )
        dialogue_state = GIEDialogueManagerService.build_initial_state(
            schema=schema,
            intake_analysis={
                "nlu": {
                    "weekly_cadence": {"raw": "4 days per week", "value": 4, "unit": "times_per_week"},
                }
            },
        )

        slot_by_key = {slot["slot_key"]: slot for slot in dialogue_state["slot_state"]}
        self.assertEqual(slot_by_key["weekly_training_days"]["status"], "filled")
        self.assertEqual(slot_by_key["weekly_training_days"]["value"], 4)
        self.assertEqual(slot_by_key["weekly_training_days"]["source"], "goal_text")
        self.assertEqual(slot_by_key["weekly_training_days"]["missing_reason"], None)

    def test_next_prompt_targets_first_missing_required_slot(self):
        schema = GIEDynamicSchemaService.generate_schema(
            goal_text="I want to run a half marathon.",
            intake_analysis={"goal_domain": {"value": "health"}},
        )
        dialogue_state = GIEDialogueManagerService.build_initial_state(
            schema=schema,
            intake_analysis={"nlu": {}},
        )
        first_required_key = schema["required_slots"][0]["key"]

        self.assertIsNotNone(dialogue_state["next_prompt"])
        self.assertEqual(dialogue_state["next_prompt"]["target_slot_key"], first_required_key)


class GIEPlanningBridgePayloadTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(email="gie-bridge@test.com", password="Password@123")
        self.session = GIESession.objects.create(
            user=self.user,
            goal_text="Save for emergency fund",
            goal_domain=GIESession.DOMAIN_FINANCIAL,
            status=GIESession.STATUS_READY_TO_FINALIZE,
            phase=GIESession.PHASE_REVIEW,
        )

    def test_run_finalize_bridge_uses_unified_context_goal_and_timeline_mapping(self):
        captured_payload = {}

        class _DummyResponse:
            status_code = status.HTTP_201_CREATED
            data = {"message": "created"}

            def render(self):
                return self

        def _fake_view(request):
            incoming = getattr(request, "data", None)
            if incoming is not None:
                captured_payload.update({key: incoming.get(key) for key in incoming.keys()})
            else:
                captured_payload.update(json.loads(request.body.decode("utf-8")))
            return _DummyResponse()

        with patch("gie.services.planning.CreateGoalWithHierarchyAPIView.as_view", return_value=_fake_view):
            result = GIEPlanningService.run_finalize_bridge(
                session=self.session,
                goal_payload={
                    "title": "Emergency Fund Goal",
                    "description": "Build a resilient emergency fund.",
                    "primary_category": "financial",
                    "priority": "high",
                    "target_date": "2027-01-15",
                    "why_do_i_want_this": "Stability for unexpected events.",
                    "specific_measurable_target": "Save 10000 by deadline.",
                    "why_it_matters": ["Stability for unexpected events."],
                    **full_goal_commitment_context(),
                },
            )

        self.assertTrue(result.ok)
        self.assertEqual(captured_payload["title"], "Emergency Fund Goal")
        self.assertEqual(captured_payload["description"], "Build a resilient emergency fund.")
        self.assertEqual(captured_payload["priority"], "high")
        self.assertEqual(captured_payload["target_date"], "2027-01-15")
        self.assertEqual(captured_payload["why_it_matters"], ["Stability for unexpected events."])
        self.assertEqual(captured_payload["why_do_i_want_this"], "Stability for unexpected events.")
        self.assertEqual(captured_payload["specific_measurable_target"], "Save 10000 by deadline.")
        self.assertEqual(captured_payload["commitment_intent"], "I am committing to this goal.")
        self.assertIn("contract_snapshot", captured_payload)

    def test_resolve_goal_priority_returns_high_for_deadline_plus_measurable_signals(self):
        slot_states = [
            GIESlotState(
                session=self.session,
                slot_key="target_date",
                required=True,
                status=GIESlotState.STATUS_FILLED,
                value=str(timezone.localdate() + timedelta(days=120)),
                source=GIESlotState.SOURCE_TURN_ANSWER,
                confidence=1.0,
            ),
            GIESlotState(
                session=self.session,
                slot_key="savings_target",
                required=True,
                status=GIESlotState.STATUS_FILLED,
                value=10000,
                source=GIESlotState.SOURCE_TURN_ANSWER,
                confidence=1.0,
            ),
        ]
        resolved = GIEPlanningService._resolve_goal_priority(
            slot_states=slot_states,
            unified_context={"raw_goal": "Save 10000 by year end", "slot_profile": {"savings_purpose": "security"}},
        )
        self.assertEqual(resolved, "high")

    def test_resolve_goal_priority_returns_low_for_exploratory_goal(self):
        resolved = GIEPlanningService._resolve_goal_priority(
            slot_states=[],
            unified_context={"raw_goal": "Maybe I should consider learning guitar someday", "slot_profile": {}},
        )
        self.assertEqual(resolved, "low")

    def test_resolve_goal_priority_keeps_explicit_slot_priority_override(self):
        slot_states = [
            GIESlotState(
                session=self.session,
                slot_key="priority",
                required=False,
                status=GIESlotState.STATUS_FILLED,
                value="low",
                source=GIESlotState.SOURCE_TURN_ANSWER,
                confidence=1.0,
            ),
            GIESlotState(
                session=self.session,
                slot_key="target_date",
                required=True,
                status=GIESlotState.STATUS_FILLED,
                value=str(timezone.localdate() + timedelta(days=90)),
                source=GIESlotState.SOURCE_TURN_ANSWER,
                confidence=1.0,
            ),
            GIESlotState(
                session=self.session,
                slot_key="savings_target",
                required=True,
                status=GIESlotState.STATUS_FILLED,
                value=12000,
                source=GIESlotState.SOURCE_TURN_ANSWER,
                confidence=1.0,
            ),
        ]
        resolved = GIEPlanningService._resolve_goal_priority(
            slot_states=slot_states,
            unified_context={"raw_goal": "Urgent save target", "slot_profile": {"savings_purpose": "security"}},
        )
        self.assertEqual(resolved, "low")

    def test_resolve_goal_priority_returns_medium_for_timeline_between_six_and_twelve_months(self):
        slot_states = [
            GIESlotState(
                session=self.session,
                slot_key="target_date",
                required=True,
                status=GIESlotState.STATUS_FILLED,
                value=str(timezone.localdate() + timedelta(days=300)),
                source=GIESlotState.SOURCE_TURN_ANSWER,
                confidence=1.0,
            ),
        ]
        resolved = GIEPlanningService._resolve_goal_priority(
            slot_states=slot_states,
            unified_context={"raw_goal": "Improve my writing quality over time", "slot_profile": {}},
        )
        self.assertEqual(resolved, "medium")

    def test_resolve_goal_priority_returns_medium_for_open_ended_goal_without_timeline(self):
        resolved = GIEPlanningService._resolve_goal_priority(
            slot_states=[],
            unified_context={"raw_goal": "I want to read more books", "slot_profile": {}},
        )
        self.assertEqual(resolved, "medium")

    def test_resolve_goal_priority_returns_high_for_user_stated_high_importance(self):
        resolved = GIEPlanningService._resolve_goal_priority(
            slot_states=[],
            unified_context={
                "raw_goal": "This is really important to me and is my top priority this year",
                "slot_profile": {},
            },
        )
        self.assertEqual(resolved, "high")

    def test_resolve_goal_priority_returns_high_for_specific_event_deadline(self):
        slot_states = [
            GIESlotState(
                session=self.session,
                slot_key="target_date",
                required=True,
                status=GIESlotState.STATUS_FILLED,
                value=str(timezone.localdate() + timedelta(days=320)),
                source=GIESlotState.SOURCE_TURN_ANSWER,
                confidence=1.0,
            ),
        ]
        resolved = GIEPlanningService._resolve_goal_priority(
            slot_states=slot_states,
            unified_context={"raw_goal": "Prepare for my interview and promotion review", "slot_profile": {}},
        )
        self.assertEqual(resolved, "high")

    def test_materialize_commitments_personalizes_running_language_from_unified_context(self):
        commitments = GIEPlanningService.materialize_commitments(
            commitments_input=[],
            plan_payload={
                "goal_summary": "Train for half marathon",
                "milestones": [{"title": "Foundation setup", "target_date": "2026-09-08"}],
            },
            unified_context={
                "slot_profile": {
                    "goal_domain": "running_endurance",
                    "weekly_training_days": 4,
                    "daily_session_minutes": 45,
                },
                "goal_details": {
                    "title": "Run First Half Marathon",
                    "measurable_target": "Complete a half marathon",
                },
                "timeline": {"end_date": "2026-09-08"},
            },
        )
        c1 = next(item for item in commitments if item["id"] == "c1")
        c2 = next(item for item in commitments if item["id"] == "c2")

        self.assertIn("I commit to", c1["statement"])
        self.assertIn("4 running sessions each week", c1["statement"])
        self.assertIn("45 minutes per session", c1["statement"])
        self.assertIn("2026-09-08", c1["statement"])
        self.assertNotIn("consistent weekly execution against this plan", c1["statement"])

        self.assertIn("every Sunday", c2["statement"])
        self.assertIn("2026-09-08", c2["statement"])
        self.assertNotIn("weekly review and adjustment cycle", c2["statement"])

    def test_materialize_commitments_personalizes_finance_language_from_unified_context(self):
        commitments = GIEPlanningService.materialize_commitments(
            commitments_input=[],
            plan_payload={
                "goal_summary": "Emergency fund goal",
                "milestones": [{"title": "Foundation setup", "target_date": "2026-12-31"}],
            },
            unified_context={
                "slot_profile": {
                    "goal_domain": "finance",
                    "savings_target": 10000,
                    "monthly_income": 4000,
                    "monthly_fixed_expenses": 2200,
                    "existing_debt": 300,
                },
                "goal_details": {
                    "title": "Emergency Fund Goal",
                    "measurable_target": "Save 10000 by 2026-12-31",
                },
                "timeline": {"end_date": "2026-12-31"},
            },
        )
        c1 = next(item for item in commitments if item["id"] == "c1")
        c2 = next(item for item in commitments if item["id"] == "c2")

        self.assertIn("on the 1st of every month", c1["statement"])
        self.assertIn("10000 savings target", c1["statement"])
        self.assertIn("2026-12-31", c1["statement"])
        self.assertIn("every Sunday", c2["statement"])

    def test_materialize_commitments_fallback_avoids_placeholder_none(self):
        commitments = GIEPlanningService.materialize_commitments(
            commitments_input=[],
            plan_payload={
                "goal_summary": "Improve skill consistency",
                "milestones": [{"title": "Foundation setup", "target_date": "2026-11-15"}],
            },
            unified_context={
                "slot_profile": {
                    "goal_domain": "skill_acquisition",
                    "daily_practice_minutes": None,
                    "learning_method": "",
                    "goal_milestone_event": "",
                    "motivation_driver": "",
                },
                "goal_details": {
                    "title": "Skill Consistency Goal",
                    "why": "to build confidence through consistency",
                    "measurable_target": "",
                },
                "timeline": {"end_date": "2026-11-15"},
            },
        )
        c1 = next(item for item in commitments if item["id"] == "c1")
        c2 = next(item for item in commitments if item["id"] == "c2")

        self.assertIn("I commit to", c1["statement"])
        self.assertIn("every day", c1["statement"])
        self.assertIn("2026-11-15", c1["statement"])
        self.assertNotIn("None", c1["statement"])

        self.assertIn("I commit to", c2["statement"])
        self.assertIn("weekly Sunday review", c2["statement"])
        self.assertIn("2026-11-15", c2["statement"])
        self.assertNotIn("None", c2["statement"])


class GIETimelineValidationServiceTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(email="timeline-service@test.com", password="Password@123")

    def _build_session(self, domain: str) -> tuple[GIESession, dict[str, GIESlotState]]:
        session = GIESession.objects.create(
            user=self.user,
            goal_text="Test goal",
            goal_domain=domain,
            status=GIESession.STATUS_ACTIVE,
            phase=GIESession.PHASE_QUESTION_LOOP,
        )
        states = [
            GIESlotState.objects.create(
                session=session,
                slot_key="timeline_target_date",
                required=True,
                status=GIESlotState.STATUS_FILLED,
                value="2026-04-10",
                source=GIESlotState.SOURCE_TURN_ANSWER,
                confidence=1.0,
                last_updated_turn_index=1,
            ),
            GIESlotState.objects.create(
                session=session,
                slot_key="weekly_availability_days",
                required=True,
                status=GIESlotState.STATUS_FILLED,
                value=3,
                source=GIESlotState.SOURCE_TURN_ANSWER,
                confidence=1.0,
                last_updated_turn_index=1,
            ),
        ]
        return session, {state.slot_key: state for state in states}

    def test_flags_unrealistic_for_short_timeline(self):
        session, state_map = self._build_session(GIESession.DOMAIN_HEALTH)
        result = GIETimelineValidationService.evaluate(
            session=session,
            slot_states_by_key=state_map,
            health_profile=None,
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.verdict, "unrealistic")
        self.assertLess(result.impact_percent, 85.0)
        self.assertRegex(result.projected_full_goal_completion_date, r"^\d{4}-\d{2}-\d{2}$")

    def test_health_profile_constraints_lower_impact(self):
        from routine.models import HealthProfile

        session, state_map = self._build_session(GIESession.DOMAIN_HEALTH)
        profile = HealthProfile.objects.create(
            user=self.user,
            stress_level="burnout",
            fitness_level="sedentary",
            sleep_pattern="irregular",
            willpower_level="low",
        )
        constrained = GIETimelineValidationService.evaluate(
            session=session,
            slot_states_by_key=state_map,
            health_profile=profile,
        )
        baseline = GIETimelineValidationService.evaluate(
            session=session,
            slot_states_by_key=state_map,
            health_profile=None,
        )
        assert constrained is not None
        assert baseline is not None
        self.assertGreater(constrained.estimated_timeline_days, baseline.estimated_timeline_days)
        self.assertLess(constrained.impact_percent, baseline.impact_percent)

    def test_returns_none_for_invalid_timeline_date(self):
        session, state_map = self._build_session(GIESession.DOMAIN_HEALTH)
        state_map["timeline_target_date"].value = "invalid-date"
        result = GIETimelineValidationService.evaluate(
            session=session,
            slot_states_by_key=state_map,
            health_profile=None,
        )
        self.assertIsNone(result)


class GIETimelineFeasibilityServiceTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(email="timeline-feas@test.com", password="Password@123")

    def test_running_domain_minimum_weeks_guardrail_returns_infeasible_contract(self):
        session = GIESession.objects.create(
            user=self.user,
            goal_text="Run a half marathon soon",
            goal_domain=GIESession.DOMAIN_HEALTH,
            status=GIESession.STATUS_READY_TO_FINALIZE,
            phase=GIESession.PHASE_REVIEW,
        )
        result = GIETimelineFeasibilityService.evaluate(
            session=session,
            slot_states=[],
            unified_context={
                "timeline": {
                    "start_date": "2026-03-12",
                    "end_date": "2026-04-01",
                    "milestone_interval_weeks": 2,
                    "domain_minimum_weeks": 12,
                }
            },
        )
        self.assertFalse(result["feasible"])
        self.assertIn("reason", result)
        self.assertGreater(len(result["options"]), 0)
        self.assertIn("adjusted_date", result["options"][0])

    def test_finance_math_guardrail_returns_infeasible_when_required_saving_exceeds_surplus(self):
        session = GIESession.objects.create(
            user=self.user,
            goal_text="Save aggressively for emergency fund",
            goal_domain=GIESession.DOMAIN_FINANCIAL,
            status=GIESession.STATUS_READY_TO_FINALIZE,
            phase=GIESession.PHASE_REVIEW,
        )
        slot_states = [
            GIESlotState(session=session, slot_key="savings_target", value=10000, required=True),
            GIESlotState(session=session, slot_key="current_savings", value=1000, required=True),
            GIESlotState(session=session, slot_key="monthly_income", value=2400, required=True),
            GIESlotState(session=session, slot_key="monthly_fixed_expenses", value=1300, required=True),
            GIESlotState(session=session, slot_key="existing_debt", value=300, required=True),
        ]
        result = GIETimelineFeasibilityService.evaluate(
            session=session,
            slot_states=slot_states,
            unified_context={
                "timeline": {
                    "start_date": "2026-03-12",
                    "end_date": "2026-09-12",
                    "milestone_interval_weeks": 2,
                    "domain_minimum_weeks": 4,
                }
            },
        )
        self.assertFalse(result["feasible"])
        self.assertIn("options", result)
        self.assertGreaterEqual(len(result["options"]), 1)

    def test_buffer_and_milestone_contract_for_feasible_case(self):
        session = GIESession.objects.create(
            user=self.user,
            goal_text="Run a half marathon this year",
            goal_domain=GIESession.DOMAIN_HEALTH,
            status=GIESession.STATUS_READY_TO_FINALIZE,
            phase=GIESession.PHASE_REVIEW,
        )
        result = GIETimelineFeasibilityService.evaluate(
            session=session,
            slot_states=[],
            unified_context={
                "timeline": {
                    "start_date": "2026-03-12",
                    "end_date": "2026-09-12",
                    "milestone_interval_weeks": 3,
                    "domain_minimum_weeks": 12,
                }
            },
        )
        self.assertTrue(result["feasible"])
        self.assertIsInstance(result["buffer_weeks"], int)
        self.assertIn(result["buffer_weeks"], (1, 2))
        self.assertIsInstance(result["milestone_count"], int)
        self.assertGreaterEqual(result["milestone_count"], 1)

    def test_milestone_density_guardrail_rejects_interval_below_two_weeks(self):
        session = GIESession.objects.create(
            user=self.user,
            goal_text="Learn guitar improvisation",
            goal_domain=GIESession.DOMAIN_LEARNING,
            status=GIESession.STATUS_READY_TO_FINALIZE,
            phase=GIESession.PHASE_REVIEW,
        )
        result = GIETimelineFeasibilityService.evaluate(
            session=session,
            slot_states=[],
            unified_context={
                "timeline": {
                    "start_date": "2026-03-12",
                    "end_date": "2026-06-12",
                    "milestone_interval_weeks": 1,
                    "domain_minimum_weeks": 8,
                }
            },
        )
        self.assertFalse(result["feasible"])
        self.assertIn("reason", result)

    def test_missing_timeline_target_returns_required_date_error(self):
        session = GIESession.objects.create(
            user=self.user,
            goal_text="Learn guitar improvisation",
            goal_domain=GIESession.DOMAIN_LEARNING,
            status=GIESession.STATUS_READY_TO_FINALIZE,
            phase=GIESession.PHASE_REVIEW,
        )
        result = GIETimelineFeasibilityService.evaluate(
            session=session,
            slot_states=[],
            unified_context={"timeline": {"start_date": "2026-03-12"}},
        )
        self.assertFalse(result["feasible"])
        self.assertIn("target date is required", result["reason"].lower())


class GIEHabitRankingServiceTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(email="habit-ranking@test.com", password="Password@123")
        self.session = GIESession.objects.create(
            user=self.user,
            goal_text="Build wealth for emergency fund",
            goal_domain=GIESession.DOMAIN_FINANCIAL,
            status=GIESession.STATUS_ACTIVE,
            phase=GIESession.PHASE_QUESTION_LOOP,
        )
        self.slot_states = [
            GIESlotState(
                session=self.session,
                slot_key="timeline_target_date",
                required=True,
                status=GIESlotState.STATUS_FILLED,
                value="2027-01-01",
                source=GIESlotState.SOURCE_TURN_ANSWER,
                confidence=1.0,
            ),
            GIESlotState(
                session=self.session,
                slot_key="monthly_saving_capacity",
                required=True,
                status=GIESlotState.STATUS_FILLED,
                value=3500,
                source=GIESlotState.SOURCE_TURN_ANSWER,
                confidence=1.0,
            ),
        ]

    def test_ranking_is_deterministic_and_capped_to_three(self):
        first = GIEHabitRankingService.rank(
            session=self.session,
            slot_states=self.slot_states,
            health_profile=None,
        )
        second = GIEHabitRankingService.rank(
            session=self.session,
            slot_states=self.slot_states,
            health_profile=None,
        )
        self.assertEqual(first, second)
        self.assertEqual(len(first), 3)
        for item in first:
            self.assertIn("habit_name", item)
            self.assertIn("rationale", item)
            self.assertTrue(item["rationale"])
            self.assertIn("2027-01-01", item["rationale"])
            self.assertNotIn("High leverage for your", item["rationale"])
            self.assertNotIn("None", item["rationale"])

    @patch("gie.services.habit_ranking.GIEUnifiedContextService.build")
    def test_rationale_is_personalized_from_slot_profile_and_timeline(self, mocked_unified_context):
        mocked_unified_context.return_value = {
            "raw_goal": "Save for emergency fund",
            "slot_profile": {
                "goal_domain": "finance",
                "completion_status": "complete",
                "savings_target": 10000,
                "target_date": "2027-01-01",
                "monthly_income": 4000,
                "monthly_fixed_expenses": 2200,
                "current_savings": 1200,
                "existing_debt": 300,
                "savings_purpose": "emergency_fund",
            },
            "goal_details": {
                "title": "Emergency Fund Goal",
                "description": "Build emergency savings with monthly consistency.",
                "why": "To reduce financial stress.",
                "measurable_target": "Save 10000 by 2027-01-01.",
                "priority": "medium",
            },
            "timeline": {
                "start_date": "2026-03-12",
                "end_date": "2027-01-01",
                "total_weeks": 42,
                "buffer_weeks": 2,
                "milestone_interval_weeks": 4,
                "feasibility_status": "feasible",
                "domain_minimum_weeks": 4,
            },
        }
        ranked = GIEHabitRankingService.rank(
            session=self.session,
            slot_states=self.slot_states,
            health_profile=None,
        )
        self.assertGreater(len(ranked), 0)
        for item in ranked:
            rationale = item["rationale"]
            self.assertIn("Emergency Fund Goal", rationale)
            self.assertIn("2027-01-01", rationale)
            self.assertTrue("10000" in rationale or "income (4000)" in rationale or "emergency_fund" in rationale)

    @patch("gie.services.habit_ranking.GIEUnifiedContextService.build")
    def test_rationale_fallback_avoids_placeholder_none_and_keeps_goal_deadline_personal_reason(
        self,
        mocked_unified_context,
    ):
        mocked_unified_context.return_value = {
            "raw_goal": "Improve consistency with weekly execution",
            "slot_profile": {
                "goal_domain": "career",
                "completion_status": "complete",
                "current_role": "",
                "target_role": "",
                "time_in_current_role": "",
                "target_timeline": "",
                "manager_feedback_on_gaps": "",
                "available_opportunities": "",
            },
            "goal_details": {
                "title": "Career Consistency Goal",
                "description": "Build consistent weekly growth output.",
                "why": "to earn stronger promotion evidence",
                "measurable_target": "",
                "priority": "medium",
            },
            "timeline": {
                "start_date": "2026-03-12",
                "end_date": "2026-12-31",
                "total_weeks": 42,
                "buffer_weeks": 2,
                "milestone_interval_weeks": 4,
                "feasibility_status": "feasible",
                "domain_minimum_weeks": 26,
            },
        }
        ranked = GIEHabitRankingService.rank(
            session=self.session,
            slot_states=self.slot_states,
            health_profile=None,
        )
        self.assertGreater(len(ranked), 0)
        for item in ranked:
            rationale = item["rationale"]
            self.assertIn("Career Consistency Goal", rationale)
            self.assertIn("2026-12-31", rationale)
            self.assertIn("promotion evidence", rationale)
            self.assertNotIn("None", rationale)


class GIEGoalStartAPITests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            email='gie-api@test.com',
            password='Password@123',
        )
        self.url = reverse("gie:goals-start")

    def test_start_requires_authentication(self):
        response = self.client.post(self.url, data={"goal_text": "Run a half marathon."}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_start_returns_contract_payload_and_persists_records(self):
        self.client.force_authenticate(user=self.user)
        payload = {
            "goal_text": "I want to run my first half marathon in 6 months and can train 4 days per week.",
        }
        response = self.client.post(self.url, data=payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(sorted(response.data.keys()), sorted(["session", "schema", "slot_state", "next_prompt"]))

        session = response.data["session"]
        self.assertEqual(session["goal_domain"], "health")
        self.assertEqual(session["status"], "active")
        self.assertEqual(session["phase"], "question_loop")
        self.assertIn("id", session)

        schema = response.data["schema"]
        self.assertIn("required_slots", schema)
        self.assertIn("optional_slots", schema)
        self.assertGreater(len(schema["required_slots"]), 0)

        required_slot_obj = schema["required_slots"][0]
        self.assertEqual(
            sorted(required_slot_obj.keys()),
            sorted(["key", "label", "description", "required", "data_type", "enum_values", "validation"]),
        )

        next_prompt = response.data["next_prompt"]
        self.assertIn("question", next_prompt)
        self.assertIn("target_slot_key", next_prompt)

        created_session = GIESession.objects.get(id=session["id"])
        self.assertEqual(created_session.user_id, self.user.id)
        self.assertEqual(created_session.turns.count(), 1)
        self.assertEqual(created_session.turns.first().role, GIETurn.ROLE_ASSISTANT)
        self.assertEqual(created_session.slot_definitions.count(), len(schema["required_slots"]) + len(schema["optional_slots"]))
        self.assertEqual(created_session.slot_states.count(), len(response.data["slot_state"]))

    def test_start_missing_goal_text_returns_locked_error_contract(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(self.url, data={}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            sorted(response.data.keys()),
            sorted(["error", "code", "details", "status"]),
        )
        self.assertEqual(response.data["error"], "validation_error")
        self.assertEqual(response.data["code"], "invalid_start_payload")
        self.assertEqual(response.data["status"], 400)
        self.assertIn("goal_text", response.data["details"])


class GIETurnStateFinalizeAPITests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(email="gie-turn@test.com", password="Password@123")
        self.other_user = user_model.objects.create_user(email="gie-other@test.com", password="Password@123")
        self.client.force_authenticate(user=self.user)
        start_resp = self.client.post(
            reverse("gie:goals-start"),
            data={"goal_text": "I want to improve my health in 6 months."},
            format="json",
        )
        self.assertEqual(start_resp.status_code, status.HTTP_201_CREATED)
        self.session_id = start_resp.data["session"]["id"]
        self.session = GIESession.objects.get(id=self.session_id)
        # Reduce required set to one deterministic integer slot for focused contract testing.
        disabled_required_keys = [
            "timeline_target_date",
            "current_fitness_baseline",
            "running_experience",
            "daily_session_minutes",
            "injury_constraints",
            "equipment_and_location",
            "motivation_driver",
        ]
        GIESlotDefinition.objects.filter(session=self.session, key__in=disabled_required_keys).update(required=False)
        GIESlotState.objects.filter(session=self.session, slot_key__in=disabled_required_keys).update(required=False)
        self.session.required_slot_count = 1
        self.session.filled_required_slot_count = 0
        self.session.completeness_percent = 0
        self.session.current_question = "How many days per week can you train?"
        self.session.save(update_fields=["required_slot_count", "filled_required_slot_count", "completeness_percent", "current_question", "updated_at"])

    def test_turn_idempotent_replay_returns_existing_turn(self):
        turn_url = reverse("gie:goals-turn", kwargs={"session_id": self.session_id})
        payload = {"client_turn_id": "turn-0001", "answer": "4 days per week"}
        first = self.client.post(turn_url, data=payload, format="json")
        second = self.client.post(turn_url, data=payload, format="json")

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(first.data["turn"]["id"], second.data["turn"]["id"])
        self.assertEqual(GIETurn.objects.filter(session=self.session, client_turn_id="turn-0001").count(), 1)

    def test_turn_idempotent_replay_ready_to_finalize_includes_goal_details_autofill_slot(self):
        turn_url = reverse("gie:goals-turn", kwargs={"session_id": self.session_id})
        payload = {"client_turn_id": "turn-0001", "answer": "4 days per week"}
        first = self.client.post(turn_url, data=payload, format="json")
        second = self.client.post(turn_url, data=payload, format="json")

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(second.data["session_status"], "ready_to_finalize")
        slot_keys = {item["slot_key"] for item in second.data["slot_updates"]}
        self.assertIn("__goal_details_autofill", slot_keys)

    def test_turn_updates_completeness_and_transitions_ready_to_finalize(self):
        turn_url = reverse("gie:goals-turn", kwargs={"session_id": self.session_id})
        response = self.client.post(
            turn_url,
            data={"client_turn_id": "turn-0002", "answer": "5"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["session_status"], "ready_to_finalize")
        self.assertEqual(response.data["completeness"]["completeness_percent"], 100.0)
        slot_keys = {item["slot_key"] for item in response.data["slot_updates"]}
        self.assertIn("__timeline_feasibility", slot_keys)
        self.assertIn("__goal_details_autofill", slot_keys)

        self.session.refresh_from_db()
        self.assertEqual(self.session.status, GIESession.STATUS_READY_TO_FINALIZE)

    @patch("gie.services.planning.GIEUnifiedContextService.build")
    def test_turn_ready_to_finalize_autofill_matches_unified_context_goal_details(self, mocked_unified_context):
        mocked_unified_context.return_value = {
            "raw_goal": "Run my first half marathon",
            "slot_profile": {"goal_domain": "running_endurance", "completion_status": "complete"},
            "goal_details": {
                "title": "Run First Half Marathon",
                "description": "Personalized description from unified context.",
                "why": "Personalized why from unified context.",
                "measurable_target": "Personalized measurable target from unified context.",
                "priority": "medium",
            },
            "timeline": {
                "start_date": "2026-03-12",
                "end_date": "2026-09-08",
                "total_weeks": 25,
                "buffer_weeks": 2,
                "milestone_interval_weeks": 4,
                "feasibility_status": "feasible",
                "domain_minimum_weeks": 12,
            },
        }
        turn_url = reverse("gie:goals-turn", kwargs={"session_id": self.session_id})
        response = self.client.post(
            turn_url,
            data={"client_turn_id": "turn-0002-autofill", "answer": "5"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["session_status"], "ready_to_finalize")

        autofill_slot = next(
            (item for item in response.data["slot_updates"] if item["slot_key"] == "__goal_details_autofill"),
            None,
        )
        self.assertIsNotNone(autofill_slot)
        assert autofill_slot is not None
        self.assertEqual(
            autofill_slot["value"],
            {
                "title": "Run First Half Marathon",
                "primary_category": "health",
                "priority": "medium",
                "description": "Personalized description from unified context.",
                "why_do_i_want_this": "Personalized why from unified context.",
                "specific_measurable_target": "Personalized measurable target from unified context.",
                "why_it_matters": ["Personalized why from unified context."],
                "target_date": "2026-09-08",
            },
        )

    def test_turn_rejects_non_active_session(self):
        self.session.status = GIESession.STATUS_FINALIZED
        self.session.save(update_fields=["status", "updated_at"])
        turn_url = reverse("gie:goals-turn", kwargs={"session_id": self.session_id})
        response = self.client.post(
            turn_url,
            data={"client_turn_id": "turn-0003", "answer": "4"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["code"], "session_not_active")

    def test_turn_enforces_ownership_for_non_owner(self):
        self.client.force_authenticate(user=self.other_user)
        turn_url = reverse("gie:goals-turn", kwargs={"session_id": self.session_id})
        response = self.client.post(
            turn_url,
            data={"client_turn_id": "turn-non-owner", "answer": "4"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["code"], "session_not_found")

    def test_turn_missing_payload_fields_returns_locked_error_contract(self):
        turn_url = reverse("gie:goals-turn", kwargs={"session_id": self.session_id})
        response = self.client.post(turn_url, data={}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(sorted(response.data.keys()), sorted(["error", "code", "details", "status"]))
        self.assertEqual(response.data["error"], "validation_error")
        self.assertEqual(response.data["code"], "invalid_turn_payload")
        self.assertEqual(response.data["status"], 400)
        self.assertIn("client_turn_id", response.data["details"])
        self.assertIn("answer", response.data["details"])

    def test_state_endpoint_enforces_ownership_and_returns_contract(self):
        state_url = reverse("gie:goals-state", kwargs={"session_id": self.session_id})
        response = self.client.get(state_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(sorted(response.data.keys()), sorted(["session", "schema", "slot_state", "completeness"]))

        self.client.force_authenticate(user=self.other_user)
        not_found_response = self.client.get(state_url)
        self.assertEqual(not_found_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(not_found_response.data["code"], "session_not_found")

    def test_state_endpoint_ready_to_finalize_includes_goal_details_autofill_slot(self):
        self._drive_session_to_ready()
        state_url = reverse("gie:goals-state", kwargs={"session_id": self.session_id})
        response = self.client.get(state_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        slot_by_key = {item["slot_key"]: item for item in response.data["slot_state"]}
        self.assertIn("__goal_details_autofill", slot_by_key)
        self.assertIsInstance(slot_by_key["__goal_details_autofill"]["value"], dict)

    @patch("gie.services.planning.GIEUnifiedContextService.build")
    def test_state_endpoint_autofill_matches_unified_context_goal_details(self, mocked_unified_context):
        mocked_unified_context.return_value = {
            "raw_goal": "Run first half marathon",
            "slot_profile": {"goal_domain": "running_endurance", "completion_status": "complete"},
            "goal_details": {
                "title": "Run First Half Marathon",
                "description": "Mapped description from unified context.",
                "why": "Mapped why from unified context.",
                "measurable_target": "Mapped measurable target from unified context.",
                "priority": "high",
            },
            "timeline": {
                "start_date": "2026-03-12",
                "end_date": "2026-09-08",
                "total_weeks": 25,
                "buffer_weeks": 2,
                "milestone_interval_weeks": 4,
                "feasibility_status": "feasible",
                "domain_minimum_weeks": 12,
            },
        }
        self._drive_session_to_ready()
        state_url = reverse("gie:goals-state", kwargs={"session_id": self.session_id})
        response = self.client.get(state_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        slot_by_key = {item["slot_key"]: item for item in response.data["slot_state"]}
        self.assertIn("__goal_details_autofill", slot_by_key)
        self.assertEqual(
            slot_by_key["__goal_details_autofill"]["value"],
            {
                "title": "Run First Half Marathon",
                "primary_category": "health",
                "priority": "high",
                "description": "Mapped description from unified context.",
                "why_do_i_want_this": "Mapped why from unified context.",
                "specific_measurable_target": "Mapped measurable target from unified context.",
                "why_it_matters": ["Mapped why from unified context."],
                "target_date": "2026-09-08",
            },
        )

    def test_autofill_endpoint_merges_goal_context_overrides_and_returns_full_payload(self):
        self._drive_session_to_ready()
        autofill_url = reverse("gie:goals-autofill", kwargs={"session_id": self.session_id})
        response = self.client.post(
            autofill_url,
            data={
                "goal_context": {
                    "description": "Override description from form",
                    "why_do_i_want_this": "Override motivation",
                    "specific_measurable_target": "Override measurable target",
                    "why_it_matters": ["Override reason one", "Override reason two"],
                    "priority": "high",
                }
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["session_id"], self.session_id)
        self.assertEqual(response.data["autofill"]["description"], "Override description from form")
        self.assertEqual(response.data["autofill"]["why_do_i_want_this"], "Override motivation")
        self.assertEqual(response.data["autofill"]["specific_measurable_target"], "Override measurable target")
        self.assertEqual(response.data["autofill"]["why_it_matters"], ["Override reason one", "Override reason two"])
        self.assertEqual(response.data["autofill"]["priority"], "high")
        self.assertIn("title", response.data["autofill"])
        self.assertIn("primary_category", response.data["autofill"])
        self.assertIn("target_date", response.data["autofill"])

    def _drive_session_to_ready(self):
        turn_url = reverse("gie:goals-turn", kwargs={"session_id": self.session_id})
        response = self.client.post(
            turn_url,
            data={"client_turn_id": "turn-ready", "answer": "4"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, GIESession.STATUS_READY_TO_FINALIZE)
        populate_running_slot_profile(self.session, timeline_days=180)
        timeline_state = GIESlotState.objects.filter(session=self.session, slot_key="timeline_target_date").first()
        if timeline_state:
            timeline_state.status = GIESlotState.STATUS_FILLED
            timeline_state.value = str(timezone.localdate() + timedelta(days=180))
            timeline_state.source = GIESlotState.SOURCE_TURN_ANSWER
            timeline_state.confidence = 1.0
            timeline_state.last_updated_turn_index = 1
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

    def _habit_suggestions(self) -> list[dict]:
        self.session.refresh_from_db()
        suggestion_state = GIESlotState.objects.filter(
            session=self.session,
            slot_key="__habit_ranked_suggestions",
        ).first()
        self.assertIsNotNone(suggestion_state)
        assert suggestion_state is not None
        self.assertIsInstance(suggestion_state.value, list)
        return suggestion_state.value

    def _habit_confirmations(self, decision: str = "accepted") -> list[dict]:
        return [
            {"habit_name": item["habit_name"], "decision": decision}
            for item in self._habit_suggestions()
        ]

    @patch("gie.services.planning.GIEPlanningService.run_finalize_bridge")
    def test_finalize_success_persists_plan_and_returns_commitments(self, mocked_bridge):
        mocked_bridge.return_value = GIEFinalizeBridgeResult(
            ok=True,
            status_code=201,
            payload={"message": "Goal created with complete hierarchy!"},
        )
        self._drive_session_to_ready()
        from routine.models import HabitTracker
        before_habits = HabitTracker.objects.filter(user=self.user).count()
        finalize_url = reverse("gie:goals-finalize", kwargs={"session_id": self.session_id})
        response = self.client.post(
            finalize_url,
            data={
                "commitments": accepted_commitment_decisions(),
                "goal_context": full_goal_commitment_context(user=self.user, include_snapshot=False),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["session_status"], "finalized")
        self.assertEqual(len(response.data["commitments"]), 2)
        self.assertIn("rie_signal", response.data)
        self.assertIn("confirmed_habits", response.data["rie_signal"])
        self.assertEqual(response.data["rie_signal"]["confirmed_habits"], [])

        self.session.refresh_from_db()
        self.assertEqual(self.session.status, GIESession.STATUS_FINALIZED)
        snapshot = GIEPlanSnapshot.objects.filter(session=self.session).order_by("-created_at").first()
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.status, GIEPlanSnapshot.STATUS_FINALIZED)
        habit_suggestion_state = self._habit_suggestions()
        self.assertLessEqual(len(habit_suggestion_state), 3)
        self.assertEqual(snapshot.rie_signal["suggested_sequence_order"], [])
        self.assertEqual(HabitTracker.objects.filter(user=self.user).count(), before_habits)

    def test_finalize_accepts_missing_habit_confirmations_and_rejects_invalid_set(self):
        self._drive_session_to_ready()
        finalize_url = reverse("gie:goals-finalize", kwargs={"session_id": self.session_id})

        missing = self.client.post(
            finalize_url,
            data={"goal_context": full_goal_commitment_context()},
            format="json",
        )
        self.assertEqual(missing.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(missing.data["code"], "binding_commitments_incomplete")

        invalid = self.client.post(
            finalize_url,
            data={
                "habit_confirmations": [{"habit_name": "Unknown habit", "decision": "accepted"}],
                "goal_context": full_goal_commitment_context(),
            },
            format="json",
        )
        self.assertEqual(invalid.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(invalid.data["code"], "invalid_habit_confirmation_payload")

    def test_finalize_rejects_missing_generated_commitment_acceptance(self):
        self._drive_session_to_ready()
        finalize_url = reverse("gie:goals-finalize", kwargs={"session_id": self.session_id})
        response = self.client.post(
            finalize_url,
            data={
                "commitments": [{"id": "c1", "decision": "accepted", "revision_note": None}],
                "goal_context": full_goal_commitment_context(user=self.user, include_snapshot=False),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "binding_commitments_incomplete")
        self.assertIn("missing_commitment_ids", response.data["details"])

    def test_finalize_rejects_non_accepted_commitment_decisions(self):
        self._drive_session_to_ready()
        finalize_url = reverse("gie:goals-finalize", kwargs={"session_id": self.session_id})
        response = self.client.post(
            finalize_url,
            data={
                "commitments": [
                    {"id": "c1", "decision": "accepted", "revision_note": None},
                    {"id": "c2", "decision": "revised", "revision_note": "Weekdays only"},
                ],
                "goal_context": full_goal_commitment_context(user=self.user, include_snapshot=False),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "binding_commitments_incomplete")
        self.assertIn("non_accepted_commitment_ids", response.data["details"])

    def test_finalize_rejects_unknown_commitment_ids(self):
        self._drive_session_to_ready()
        finalize_url = reverse("gie:goals-finalize", kwargs={"session_id": self.session_id})
        response = self.client.post(
            finalize_url,
            data={
                "commitments": [
                    {"id": "c1", "decision": "accepted", "revision_note": None},
                    {"id": "c2", "decision": "accepted", "revision_note": None},
                    {"id": "c999", "decision": "accepted", "revision_note": None},
                ],
                "goal_context": full_goal_commitment_context(user=self.user, include_snapshot=False),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "binding_commitments_incomplete")
        self.assertIn("unknown_commitment_ids", response.data["details"])

    def test_finalize_rejects_mismatched_contract_snapshot(self):
        self._drive_session_to_ready()
        finalize_url = reverse("gie:goals-finalize", kwargs={"session_id": self.session_id})
        response = self.client.post(
            finalize_url,
            data={
                "commitments": accepted_commitment_decisions(),
                "goal_context": full_goal_commitment_context(
                    user=self.user,
                    accepted_commitments=[],
                ),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "contract_snapshot_mismatch")

    def test_finalize_rejects_goal_context_when_commitment_not_accepted(self):
        self._drive_session_to_ready()
        finalize_url = reverse("gie:goals-finalize", kwargs={"session_id": self.session_id})
        response = self.client.post(
            finalize_url,
            data={
                "goal_context": full_goal_commitment_context(commitment_confirmed=False),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "invalid_finalize_payload")
        self.assertIn("goal_context", response.data["details"])

    def test_finalize_rejects_incomplete_commitment_payload_in_goal_context(self):
        self._drive_session_to_ready()
        finalize_url = reverse("gie:goals-finalize", kwargs={"session_id": self.session_id})
        response = self.client.post(
            finalize_url,
            data={
                "goal_context": {
                    **full_goal_commitment_context(),
                    "commitment_effort": "",
                    "contract_snapshot": {},
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "invalid_finalize_payload")
        self.assertIn("goal_context", response.data["details"])

    def test_finalize_enforces_ownership_for_non_owner(self):
        self._drive_session_to_ready()
        finalize_url = reverse("gie:goals-finalize", kwargs={"session_id": self.session_id})
        self.client.force_authenticate(user=self.other_user)
        response = self.client.post(finalize_url, data={"commitments": []}, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["code"], "session_not_found")

    def test_finalize_invalid_payload_returns_locked_error_contract(self):
        self._drive_session_to_ready()
        finalize_url = reverse("gie:goals-finalize", kwargs={"session_id": self.session_id})
        response = self.client.post(
            finalize_url,
            data={
                "commitments": [{"id": "c1", "decision": "invalid_value", "revision_note": None}],
                "habit_confirmations": [],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(sorted(response.data.keys()), sorted(["error", "code", "details", "status"]))
        self.assertEqual(response.data["error"], "validation_error")
        self.assertEqual(response.data["code"], "invalid_finalize_payload")
        self.assertEqual(response.data["status"], 400)
        self.assertIn("commitments", response.data["details"])

    @patch("gie.services.planning.GIEPlanningService.run_finalize_bridge")
    def test_finalize_bridge_failure_rolls_back_to_ready_to_finalize(self, mocked_bridge):
        self._drive_session_to_ready()
        mocked_bridge.return_value = GIEFinalizeBridgeResult(
            ok=False,
            status_code=500,
            payload={"error": "bridge_failure"},
        )
        finalize_url = reverse("gie:goals-finalize", kwargs={"session_id": self.session_id})
        response = self.client.post(
            finalize_url,
            data={
                "commitments": accepted_commitment_decisions(),
                "goal_context": full_goal_commitment_context(user=self.user, include_snapshot=False),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["code"], "finalize_bridge_failed")
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, GIESession.STATUS_READY_TO_FINALIZE)
        self.assertEqual(GIEPlanSnapshot.objects.filter(session=self.session).count(), 0)

    @patch("gie.services.planning.GIEPlanningService.run_finalize_bridge")
    def test_finalize_retry_after_bridge_failure_succeeds(self, mocked_bridge):
        self._drive_session_to_ready()
        mocked_bridge.side_effect = [
            GIEFinalizeBridgeResult(ok=False, status_code=500, payload={"error": "bridge_failure"}),
            GIEFinalizeBridgeResult(ok=True, status_code=201, payload={"message": "Goal created with complete hierarchy!"}),
        ]
        finalize_url = reverse("gie:goals-finalize", kwargs={"session_id": self.session_id})
        payload = {
            "commitments": accepted_commitment_decisions(),
            "goal_context": full_goal_commitment_context(user=self.user, include_snapshot=False),
        }

        first_response = self.client.post(finalize_url, data=payload, format="json")
        self.assertEqual(first_response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(first_response.data["code"], "finalize_bridge_failed")
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, GIESession.STATUS_READY_TO_FINALIZE)
        self.assertEqual(GIEPlanSnapshot.objects.filter(session=self.session).count(), 0)

        second_response = self.client.post(finalize_url, data=payload, format="json")
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        self.assertEqual(second_response.data["session_status"], "finalized")
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, GIESession.STATUS_FINALIZED)
        self.assertEqual(GIEPlanSnapshot.objects.filter(session=self.session).count(), 1)

    def test_finalize_blocks_missing_required_slots(self):
        finalize_url = reverse("gie:goals-finalize", kwargs={"session_id": self.session_id})
        response = self.client.post(
            finalize_url,
            data={"commitments": []},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["code"], "session_not_ready_to_finalize")

        self.session.status = GIESession.STATUS_READY_TO_FINALIZE
        self.session.save(update_fields=["status", "updated_at"])
        response = self.client.post(finalize_url, data={"commitments": []}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "required_slots_missing")

    @patch("gie.services.planning.GIEPlanningService.run_finalize_bridge")
    def test_finalize_returns_warning_when_timeline_feasibility_is_infeasible(self, mocked_bridge):
        mocked_bridge.return_value = GIEFinalizeBridgeResult(
            ok=True,
            status_code=201,
            payload={"message": "Goal created with complete hierarchy!", "goal": {"id": "g-1"}},
        )
        self._drive_session_to_ready()
        timeline_state = GIESlotState.objects.get(session=self.session, slot_key="timeline_target_date")
        timeline_state.value = str(timezone.localdate() + timedelta(days=14))
        timeline_state.save(update_fields=["value", "updated_at"])

        finalize_url = reverse("gie:goals-finalize", kwargs={"session_id": self.session_id})
        response = self.client.post(
            finalize_url,
            data={
                "commitments": accepted_commitment_decisions(),
                "goal_context": full_goal_commitment_context(user=self.user, include_snapshot=False),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["session_status"], "finalized")
        self.assertIn("feasibility", response.data)
        self.assertEqual(response.data["feasibility"]["is_feasible"], False)
        self.assertGreaterEqual(len(response.data["feasibility"]["warnings"]), 1)
        mocked_bridge.assert_called_once()

    @patch("gie.services.planning.GIEPlanningService.run_finalize_bridge")
    def test_plan_endpoint_returns_latest_and_404_when_missing(self, mocked_bridge):
        mocked_bridge.return_value = GIEFinalizeBridgeResult(
            ok=True,
            status_code=201,
            payload={"message": "Goal created with complete hierarchy!"},
        )
        plan_url = reverse("gie:goals-plan", kwargs={"session_id": self.session_id})
        missing_response = self.client.get(plan_url)
        self.assertEqual(missing_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(missing_response.data["code"], "plan_snapshot_not_found")

        self._drive_session_to_ready()
        finalize_url = reverse("gie:goals-finalize", kwargs={"session_id": self.session_id})
        finalize_response = self.client.post(
            finalize_url,
            data={
                "commitments": accepted_commitment_decisions(),
                "goal_context": full_goal_commitment_context(user=self.user, include_snapshot=False),
            },
            format="json",
        )
        self.assertEqual(finalize_response.status_code, status.HTTP_200_OK)

        plan_response = self.client.get(plan_url)
        self.assertEqual(plan_response.status_code, status.HTTP_200_OK)
        self.assertEqual(plan_response.data["session_id"], self.session_id)
        self.assertIn("plan_snapshot", plan_response.data)
        self.assertIn("rie_signal", plan_response.data["plan_snapshot"])

    @patch("gie.services.planning.GIEPlanningService.run_finalize_bridge")
    def test_plan_endpoint_enforces_ownership_for_non_owner(self, mocked_bridge):
        mocked_bridge.return_value = GIEFinalizeBridgeResult(
            ok=True,
            status_code=201,
            payload={"message": "Goal created with complete hierarchy!"},
        )
        self._drive_session_to_ready()
        finalize_url = reverse("gie:goals-finalize", kwargs={"session_id": self.session_id})
        _ = self.client.post(
            finalize_url,
            data={
                "commitments": accepted_commitment_decisions(),
                "goal_context": full_goal_commitment_context(user=self.user, include_snapshot=False),
            },
            format="json",
        )
        self.client.force_authenticate(user=self.other_user)
        plan_url = reverse("gie:goals-plan", kwargs={"session_id": self.session_id})
        response = self.client.get(plan_url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["code"], "session_not_found")


class GIELifecycleContractIntegrationTests(APITestCase):
    @patch("gie.services.planning.GIEPlanningService.run_finalize_bridge")
    def test_full_lifecycle_start_turn_state_finalize_plan_adapt(self, mocked_bridge):
        user_model = get_user_model()
        user = user_model.objects.create_user(email="gie-lifecycle@test.com", password="Password@123")
        self.client.force_authenticate(user=user)
        mocked_bridge.return_value = GIEFinalizeBridgeResult(
            ok=True,
            status_code=201,
            payload={"message": "Goal created with complete hierarchy!"},
        )

        start_response = self.client.post(
            reverse("gie:goals-start"),
            data={"goal_text": "I want to improve my health in six months."},
            format="json",
        )
        self.assertEqual(start_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(sorted(start_response.data.keys()), sorted(["session", "schema", "slot_state", "next_prompt"]))
        session_id = start_response.data["session"]["id"]
        session = GIESession.objects.get(id=session_id)

        # Reduce required slots so lifecycle can run deterministically in one turn.
        disabled_required_keys = [
            "timeline_target_date",
            "current_fitness_baseline",
            "running_experience",
            "daily_session_minutes",
            "injury_constraints",
            "equipment_and_location",
            "motivation_driver",
        ]
        GIESlotDefinition.objects.filter(
            session=session,
            key__in=disabled_required_keys,
        ).update(required=False)
        GIESlotState.objects.filter(
            session=session,
            slot_key__in=disabled_required_keys,
        ).update(required=False)
        session.required_slot_count = 1
        session.filled_required_slot_count = 0
        session.completeness_percent = 0
        session.current_question = "How many days per week can you train?"
        session.save(
            update_fields=[
                "required_slot_count",
                "filled_required_slot_count",
                "completeness_percent",
                "current_question",
                "updated_at",
            ]
        )

        turn_response = self.client.post(
            reverse("gie:goals-turn", kwargs={"session_id": session_id}),
            data={"client_turn_id": "turn-lifecycle-1", "answer": "4"},
            format="json",
        )
        self.assertEqual(turn_response.status_code, status.HTTP_200_OK)
        self.assertEqual(sorted(turn_response.data.keys()), sorted(["session_id", "turn", "slot_updates", "completeness", "next_prompt", "session_status"]))
        self.assertEqual(turn_response.data["session_status"], "ready_to_finalize")
        populate_running_slot_profile(session, timeline_days=180)

        state_response = self.client.get(reverse("gie:goals-state", kwargs={"session_id": session_id}))
        self.assertEqual(state_response.status_code, status.HTTP_200_OK)
        self.assertEqual(sorted(state_response.data.keys()), sorted(["session", "schema", "slot_state", "completeness"]))

        finalize_response = self.client.post(
            reverse("gie:goals-finalize", kwargs={"session_id": session_id}),
            data={
                "commitments": accepted_commitment_decisions(),
                "goal_context": full_goal_commitment_context(user=user, include_snapshot=False),
            },
            format="json",
        )
        self.assertEqual(finalize_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            sorted(finalize_response.data.keys()),
            sorted(["session_id", "session_status", "plan_snapshot", "commitments", "rie_signal", "goal", "goal_generation", "feasibility"]),
        )
        self.assertEqual(finalize_response.data["session_status"], "finalized")

        plan_response = self.client.get(reverse("gie:goals-plan", kwargs={"session_id": session_id}))
        self.assertEqual(plan_response.status_code, status.HTTP_200_OK)
        self.assertEqual(sorted(plan_response.data.keys()), sorted(["session_id", "plan_snapshot"]))

        adapt_response = self.client.post(
            reverse("gie:goals-adapt", kwargs={"session_id": session_id}),
            data={
                "signals": [
                    {
                        "signal_type": "progress",
                        "trigger": "declining_engagement",
                        "value": "high",
                        "observed_at": "2026-03-17T07:10:00Z",
                    }
                ]
            },
            format="json",
        )
        self.assertEqual(adapt_response.status_code, status.HTTP_200_OK)
        self.assertEqual(sorted(adapt_response.data.keys()), sorted(["session_id", "proposal"]))
        self.assertIn("trigger", adapt_response.data["proposal"])
        self.assertIn("action", adapt_response.data["proposal"])

    def test_full_lifecycle_finalize_executes_real_bridge_and_creates_goal(self):
        user_model = get_user_model()
        user = user_model.objects.create_user(email="gie-lifecycle-realbridge@test.com", password="Password@123")
        self.client.force_authenticate(user=user)

        start_response = self.client.post(
            reverse("gie:goals-start"),
            data={"goal_text": "I want to improve my health in six months."},
            format="json",
        )
        self.assertEqual(start_response.status_code, status.HTTP_201_CREATED)
        session_id = start_response.data["session"]["id"]
        session = GIESession.objects.get(id=session_id)

        disabled_required_keys = [
            "timeline_target_date",
            "current_fitness_baseline",
            "running_experience",
            "daily_session_minutes",
            "injury_constraints",
            "equipment_and_location",
            "motivation_driver",
        ]
        GIESlotDefinition.objects.filter(
            session=session,
            key__in=disabled_required_keys,
        ).update(required=False)
        GIESlotState.objects.filter(
            session=session,
            slot_key__in=disabled_required_keys,
        ).update(required=False)
        session.required_slot_count = 1
        session.filled_required_slot_count = 0
        session.completeness_percent = 0
        session.current_question = "How many days per week can you train?"
        session.save(
            update_fields=[
                "required_slot_count",
                "filled_required_slot_count",
                "completeness_percent",
                "current_question",
                "updated_at",
            ]
        )

        turn_response = self.client.post(
            reverse("gie:goals-turn", kwargs={"session_id": session_id}),
            data={"client_turn_id": "turn-lifecycle-real-1", "answer": "4"},
            format="json",
        )
        self.assertEqual(turn_response.status_code, status.HTTP_200_OK)
        self.assertEqual(turn_response.data["session_status"], "ready_to_finalize")
        populate_running_slot_profile(session, timeline_days=180)

        goals_before = Goal.objects.filter(user=user).count()
        finalize_response = self.client.post(
            reverse("gie:goals-finalize", kwargs={"session_id": session_id}),
            data={
                "commitments": accepted_commitment_decisions(),
                "goal_context": full_goal_commitment_context(user=user, include_snapshot=False),
            },
            format="json",
        )
        self.assertEqual(finalize_response.status_code, status.HTTP_200_OK)
        self.assertEqual(finalize_response.data["session_status"], "finalized")
        self.assertEqual(GIEPlanSnapshot.objects.filter(session_id=session_id).count(), 1)

        goals_after = Goal.objects.filter(user=user).count()
        self.assertEqual(goals_after, goals_before + 1)
        created_goal = Goal.objects.filter(user=user).order_by("-created_at").first()
        self.assertIsNotNone(created_goal)
        assert created_goal is not None
        self.assertEqual(created_goal.title, "I want to improve my health in six months.")
        record = GoalCommitmentRecord.objects.get(goal=created_goal)
        self.assertEqual(record.user, user)
        self.assertEqual(record.signed_name, "GIE Test User")
        expected_snapshot = full_goal_commitment_context(user=user)["contract_snapshot"]
        self.assertEqual(record.contract_snapshot["version"], expected_snapshot["version"])
        self.assertEqual(record.contract_snapshot["category"], expected_snapshot["category"])
        self.assertEqual(record.contract_snapshot["gie_commitments"][0]["id"], "c1")
        self.assertEqual(record.contract_snapshot["gie_commitments"][1]["id"], "c2")

        self.assertEqual(len(finalize_response.data["commitments"]), 2)
        commitment_by_id = {item["id"]: item for item in finalize_response.data["commitments"]}
        self.assertEqual(commitment_by_id["c1"]["decision"], "accepted")
        self.assertEqual(commitment_by_id["c2"]["decision"], "accepted")


class GIETimelineReframeFlowAPITests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(email="gie-reframe@test.com", password="Password@123")
        self.client.force_authenticate(user=self.user)
        start_resp = self.client.post(
            reverse("gie:goals-start"),
            data={"goal_text": "Run a marathon in one month while working full time."},
            format="json",
        )
        self.assertEqual(start_resp.status_code, status.HTTP_201_CREATED)
        self.session_id = start_resp.data["session"]["id"]
        self.session = GIESession.objects.get(id=self.session_id)

        # Narrow to deterministic two-slot intake so the timeline check path is explicit.
        keep_required = {"timeline_target_date", "weekly_training_days"}
        GIESlotDefinition.objects.filter(session=self.session).exclude(key__in=keep_required).update(required=False)
        GIESlotState.objects.filter(session=self.session).exclude(slot_key__in=keep_required).update(required=False)
        GIESlotDefinition.objects.filter(session=self.session, key="timeline_target_date").update(required=True)
        GIESlotState.objects.filter(session=self.session, slot_key="timeline_target_date").update(required=True)
        self.session.required_slot_count = 2
        self.session.filled_required_slot_count = 0
        self.session.completeness_percent = 0
        self.session.current_question = "By what date do you want to achieve this goal?"
        self.session.save(
            update_fields=[
                "required_slot_count",
                "filled_required_slot_count",
                "completeness_percent",
                "current_question",
                "updated_at",
            ]
        )

    def _submit_turn(self, client_turn_id: str, answer: str):
        return self.client.post(
            reverse("gie:goals-turn", kwargs={"session_id": self.session_id}),
            data={"client_turn_id": client_turn_id, "answer": answer},
            format="json",
        )

    def test_unrealistic_timeline_blocks_ready_to_finalize_until_decision(self):
        first = self._submit_turn("turn-1", "2026-04-01")
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(first.data["session_status"], "active")
        second = self._submit_turn("turn-2", "2")
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(second.data["session_status"], "active")
        self.assertEqual(second.data["next_prompt"]["target_slot_key"], TIMELINE_REFRAME_DECISION_KEY)
        self.assertIn("unrealistic", second.data["next_prompt"]["question"].lower())

        state = self.client.get(reverse("gie:goals-state", kwargs={"session_id": self.session_id}))
        self.assertEqual(state.status_code, status.HTTP_200_OK)
        state_map = {item["slot_key"]: item for item in state.data["slot_state"]}
        self.assertEqual(state_map[TIMELINE_REFRAME_ANALYSIS_KEY]["value"]["verdict"], "unrealistic")
        self.assertIsNone(state_map[TIMELINE_REFRAME_DECISION_KEY]["value"])

    def test_accept_reframe_branch_transitions_to_ready_to_finalize(self):
        self._submit_turn("turn-1", "2026-04-01")
        self._submit_turn("turn-2", "2")
        decision = self._submit_turn("turn-3", "accept_reframed_plan")
        self.assertEqual(decision.status_code, status.HTTP_200_OK)
        self.assertEqual(decision.data["session_status"], "ready_to_finalize")

        self.session.refresh_from_db()
        self.assertEqual(self.session.status, GIESession.STATUS_READY_TO_FINALIZE)

    def test_finalize_rejects_unresolved_reframe_even_if_status_is_forced_ready(self):
        self._submit_turn("turn-1", "2026-04-01")
        self._submit_turn("turn-2", "2")
        self.session.refresh_from_db()
        self.session.status = GIESession.STATUS_READY_TO_FINALIZE
        self.session.phase = GIESession.PHASE_REVIEW
        self.session.save(update_fields=["status", "phase", "updated_at"])

        response = self.client.post(
            reverse("gie:goals-finalize", kwargs={"session_id": self.session_id}),
            data={"commitments": []},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["code"], "timeline_reframe_unresolved")

    def test_manual_adjust_branch_updates_target_date_and_resolves(self):
        self._submit_turn("turn-1", "2026-04-01")
        self._submit_turn("turn-2", "2")
        decision = self._submit_turn("turn-3", "adjust_timeline:2027-02-01")
        self.assertEqual(decision.status_code, status.HTTP_200_OK)
        self.assertEqual(decision.data["session_status"], "ready_to_finalize")

        state = self.client.get(reverse("gie:goals-state", kwargs={"session_id": self.session_id}))
        state_map = {item["slot_key"]: item for item in state.data["slot_state"]}
        self.assertEqual(state_map["timeline_target_date"]["value"], "2027-02-01")
        self.assertIn(
            state_map[TIMELINE_REFRAME_DECISION_KEY]["value"]["decision"],
            {"adjust_manually", "timeline_realistic"},
        )


class GIEAdaptationAPITests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(email="gie-adapt@test.com", password="Password@123")
        self.other_user = user_model.objects.create_user(email="gie-adapt-other@test.com", password="Password@123")
        self.client.force_authenticate(user=self.user)
        start_resp = self.client.post(
            reverse("gie:goals-start"),
            data={"goal_text": "I want to run my first half marathon in 6 months."},
            format="json",
        )
        self.assertEqual(start_resp.status_code, status.HTTP_201_CREATED)
        self.session_id = start_resp.data["session"]["id"]

    def test_adapt_requires_authentication(self):
        self.client.force_authenticate(user=None)
        url = reverse("gie:goals-adapt", kwargs={"session_id": self.session_id})
        response = self.client.post(
            url,
            data={"signals": [{"signal_type": "routine", "trigger": "missed_tasks_streak", "value": 4, "observed_at": "2026-03-17T07:00:00Z"}]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_adapt_returns_locked_validation_error_contract(self):
        url = reverse("gie:goals-adapt", kwargs={"session_id": self.session_id})
        response = self.client.post(url, data={"signals": []}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "validation_error")
        self.assertEqual(response.data["code"], "invalid_adaptation_signal_payload")
        self.assertIn("signals", response.data["details"])

    def test_adapt_enforces_ownership(self):
        self.client.force_authenticate(user=self.other_user)
        url = reverse("gie:goals-adapt", kwargs={"session_id": self.session_id})
        response = self.client.post(
            url,
            data={"signals": [{"signal_type": "routine", "trigger": "missed_tasks_streak", "value": 4, "observed_at": "2026-03-17T07:00:00Z"}]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["code"], "session_not_found")

    def test_adapt_persists_proposal_and_changes_by_trigger(self):
        url = reverse("gie:goals-adapt", kwargs={"session_id": self.session_id})

        missed_response = self.client.post(
            url,
            data={
                "signals": [
                    {
                        "signal_type": "routine",
                        "trigger": "missed_tasks_streak",
                        "value": 4,
                        "observed_at": "2026-03-17T07:00:00Z",
                    }
                ]
            },
            format="json",
        )
        self.assertEqual(missed_response.status_code, status.HTTP_200_OK)
        self.assertEqual(missed_response.data["proposal"]["trigger"], "missed_tasks_streak")
        self.assertEqual(missed_response.data["proposal"]["action"], "reduce_scope")

        engagement_response = self.client.post(
            url,
            data={
                "signals": [
                    {
                        "signal_type": "progress",
                        "trigger": "declining_engagement",
                        "value": "high",
                        "observed_at": "2026-03-17T07:10:00Z",
                    }
                ]
            },
            format="json",
        )
        self.assertEqual(engagement_response.status_code, status.HTTP_200_OK)
        self.assertEqual(engagement_response.data["proposal"]["trigger"], "declining_engagement")
        self.assertEqual(engagement_response.data["proposal"]["action"], "increase_support")

        self.assertEqual(
            GIEAdaptationProposal.objects.filter(session_id=self.session_id).count(),
            2,
        )


class GIEObservabilityAndRolloutTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(email="gie-observability@test.com", password="Password@123")
        self.client.force_authenticate(user=self.user)

    def _start_session(self, goal_text: str = "I want to improve my health in 6 months.") -> str:
        response = self.client.post(
            reverse("gie:goals-start"),
            data={"goal_text": goal_text},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.data["session"]["id"]

    @staticmethod
    def _reduce_required_slots_to_one(session: GIESession) -> None:
        disabled_required_keys = [
            "timeline_target_date",
            "current_fitness_baseline",
            "running_experience",
            "daily_session_minutes",
            "injury_constraints",
            "equipment_and_location",
            "motivation_driver",
        ]
        GIESlotDefinition.objects.filter(
            session=session,
            key__in=disabled_required_keys,
        ).update(required=False)
        GIESlotState.objects.filter(
            session=session,
            slot_key__in=disabled_required_keys,
        ).update(required=False)
        session.required_slot_count = 1
        session.filled_required_slot_count = 0
        session.completeness_percent = 0
        session.current_question = "How many days per week can you train?"
        session.save(
            update_fields=[
                "required_slot_count",
                "filled_required_slot_count",
                "completeness_percent",
                "current_question",
                "updated_at",
            ]
        )

    @patch("gie.services.planning.GIEPlanningService.run_finalize_bridge")
    def test_analytics_lifecycle_tracks_turn_ready_and_finalize(self, mocked_bridge):
        mocked_bridge.return_value = GIEFinalizeBridgeResult(
            ok=True,
            status_code=201,
            payload={"message": "Goal created with complete hierarchy!"},
        )
        session_id = self._start_session()
        session = GIESession.objects.get(id=session_id)
        self._reduce_required_slots_to_one(session)

        turn_response = self.client.post(
            reverse("gie:goals-turn", kwargs={"session_id": session_id}),
            data={"client_turn_id": "turn-observability-1", "answer": "4"},
            format="json",
        )
        self.assertEqual(turn_response.status_code, status.HTTP_200_OK)
        self.assertEqual(turn_response.data["session_status"], "ready_to_finalize")
        populate_running_slot_profile(session, timeline_days=180)

        analytics = GIESessionAnalytics.objects.get(session_id=session_id)
        self.assertEqual(analytics.turn_count, 1)
        self.assertEqual(analytics.turns_to_ready_to_finalize, 1)
        self.assertTrue(analytics.plan_review_entered)
        self.assertGreaterEqual(len(analytics.schema_completeness_progress), 1)

        _ = self.client.get(reverse("gie:goals-state", kwargs={"session_id": session_id}))

        finalize_response = self.client.post(
            reverse("gie:goals-finalize", kwargs={"session_id": session_id}),
            data={
                "commitments": accepted_commitment_decisions(),
                "goal_context": full_goal_commitment_context(user=self.user, include_snapshot=False),
            },
            format="json",
        )
        self.assertEqual(finalize_response.status_code, status.HTTP_200_OK)

        analytics.refresh_from_db()
        self.assertTrue(analytics.plan_accepted)
        self.assertEqual(analytics.finalize_success_count, 1)
        self.assertIsNotNone(analytics.time_to_finalize_seconds)
        self.assertEqual(analytics.last_stage, GIESessionAnalytics.STAGE_FINALIZED)

    def test_observability_aggregations_are_deterministic(self):
        sessions = [
            GIESession.objects.create(
                user=self.user,
                goal_text=f"Goal {idx}",
                goal_domain=GIESession.DOMAIN_HEALTH,
                status=GIESession.STATUS_ACTIVE,
                phase=GIESession.PHASE_QUESTION_LOOP,
            )
            for idx in range(3)
        ]
        GIESessionAnalytics.objects.create(
            session=sessions[0],
            turns_to_ready_to_finalize=3,
            plan_review_entered=True,
            plan_accepted=True,
            drop_off_stage=GIESessionAnalytics.STAGE_REVIEW,
        )
        GIESessionAnalytics.objects.create(
            session=sessions[1],
            turns_to_ready_to_finalize=5,
            plan_review_entered=True,
            plan_accepted=False,
            drop_off_stage=GIESessionAnalytics.STAGE_QUESTION_LOOP,
        )
        GIESessionAnalytics.objects.create(
            session=sessions[2],
            turns_to_ready_to_finalize=7,
            plan_review_entered=True,
            plan_accepted=True,
        )

        self.assertEqual(GIEObservabilityService.median_turn_count_to_ready(), 5.0)
        self.assertEqual(GIEObservabilityService.plan_acceptance_rate(), 66.67)
        self.assertEqual(
            GIEObservabilityService.drop_off_distribution(),
            {
                GIESessionAnalytics.STAGE_QUESTION_LOOP: 1,
                GIESessionAnalytics.STAGE_REVIEW: 1,
            },
        )

    @override_settings(GIE_ROLLOUT_ENABLED=False)
    def test_rollout_disabled_returns_recoverable_contract(self):
        response = self.client.post(
            reverse("gie:goals-start"),
            data={"goal_text": "Build a writing habit this quarter."},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data["error"], "service_unavailable")
        self.assertEqual(response.data["code"], "gie_rollout_disabled")
        self.assertIn("recoverable", response.data["details"])

    def test_degraded_mode_blocks_turn_and_records_fallback_signal(self):
        session_id = self._start_session()
        with override_settings(GIE_DEGRADED_MODE=True):
            response = self.client.post(
                reverse("gie:goals-turn", kwargs={"session_id": session_id}),
                data={"client_turn_id": "turn-degraded-1", "answer": "4"},
                format="json",
            )
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data["error"], "service_unavailable")
        self.assertEqual(response.data["code"], "gie_service_degraded")

        analytics = GIESessionAnalytics.objects.get(session_id=session_id)
        self.assertEqual(analytics.degradation_event_count, 1)
        self.assertEqual(analytics.fallback_activation_count, 1)
        self.assertEqual(analytics.last_fallback_reason_code, "gie_service_degraded")
