from django.contrib.auth import get_user_model
from django.test import TestCase

from gie.models import GIESession, GIESlotState
from gie.services.dynamic_schema import GIEDynamicSchemaService
from gie.services.habit_ranking import GIEHabitRankingService
from gie.services.planning import GIEPlanningService


GIE_PROMPT_GOLDEN_FIXTURES = {
    "career": {
        "goal_text": "Earn a senior machine learning engineer promotion in 12 months.",
        "timeline_target_date": "2027-03-01",
        "capacity_slot_key": "weekly_effort_hours",
        "capacity_value": 6,
        "required_slot_keys": [
            "desired_role",
            "timeline_target_date",
            "weekly_effort_hours",
            "current_experience_level",
        ],
        "optional_slot_keys": ["target_company_type", "compensation_target", "skill_focus_areas"],
        "top_habits": [
            "Track outcomes and wins every Friday",
            "Weekly feedback request from mentor/peer",
            "Daily 45-minute deep-work block",
        ],
    },
    "health": {
        "goal_text": "Run a half marathon safely while balancing work.",
        "timeline_target_date": "2027-03-01",
        "capacity_slot_key": "weekly_availability_days",
        "capacity_value": 4,
        "required_slot_keys": [
            "timeline_target_date",
            "weekly_availability_days",
            "current_fitness_baseline",
            "injury_constraints",
        ],
        "optional_slot_keys": ["preferred_workout_type", "available_equipment", "sleep_hours_target"],
        "top_habits": [
            "Hydrate before every workout",
            "Track recovery and soreness daily",
            "Sleep 7+ hours before training days",
        ],
    },
    "financial": {
        "goal_text": "Build a strong emergency fund and improve savings consistency.",
        "timeline_target_date": "2027-03-01",
        "capacity_slot_key": "weekly_commitment_hours",
        "capacity_value": 4,
        "required_slot_keys": [
            "target_amount",
            "timeline_target_date",
            "current_saved_amount",
            "monthly_saving_capacity",
        ],
        "optional_slot_keys": ["risk_tolerance", "expense_reduction_focus", "emergency_buffer_months"],
        "top_habits": [
            "Automate monthly transfer to goal fund",
            "Use a 24-hour rule for non-essential purchases",
            "Log every discretionary spend daily",
        ],
    },
    "learning": {
        "goal_text": "Become job-ready in data engineering within one year.",
        "timeline_target_date": "2027-03-01",
        "capacity_slot_key": "weekly_study_hours",
        "capacity_value": 8,
        "required_slot_keys": [
            "primary_skill_topic",
            "proficiency_target",
            "timeline_target_date",
            "weekly_study_hours",
        ],
        "optional_slot_keys": ["preferred_learning_mode", "certification_goal", "practice_project_theme"],
        "top_habits": [
            "Weekly review and weak-topic backlog",
            "Active recall session after each study block",
            "Study on fixed weekly slots",
        ],
    },
    "personal": {
        "goal_text": "Improve consistency and self-discipline in daily life.",
        "timeline_target_date": "2027-03-01",
        "capacity_slot_key": "weekly_commitment_hours",
        "capacity_value": 5,
        "required_slot_keys": [
            "personal_outcome",
            "success_definition",
            "timeline_target_date",
            "weekly_commitment_hours",
        ],
        "optional_slot_keys": ["support_system", "blockers", "accountability_method"],
        "top_habits": [
            "10-minute daily reflection",
            "Weekly accountability message",
            "Weekly planning checkpoint",
        ],
    },
    "business": {
        "goal_text": "Increase pipeline quality and improve revenue predictability.",
        "timeline_target_date": "2027-03-01",
        "capacity_slot_key": "weekly_execution_hours",
        "capacity_value": 7,
        "required_slot_keys": [
            "business_outcome",
            "target_metric",
            "timeline_target_date",
            "weekly_execution_hours",
        ],
        "optional_slot_keys": ["market_focus", "budget_available", "risk_constraints"],
        "top_habits": [
            "Customer feedback capture after each call",
            "Weekly metric review and correction",
            "Daily pipeline or distribution action",
        ],
    },
    "other": {
        "goal_text": "Ship meaningful progress every week on my personal priority.",
        "timeline_target_date": "2027-03-01",
        "capacity_slot_key": "weekly_commitment_hours",
        "capacity_value": 4,
        "required_slot_keys": [
            "goal_outcome",
            "success_metric",
            "timeline_target_date",
            "weekly_commitment_hours",
        ],
        "optional_slot_keys": ["constraints", "resources_available", "priority_tradeoffs"],
        "top_habits": [
            "Define tomorrow's first action nightly",
            "Track one leading indicator daily",
            "Weekly progress review and next-step lock",
        ],
    },
}


class GIEPromptQualityGoldenFixtureTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(email="gie-quality@test.com", password="Password@123")

    def _build_session(self, *, domain: str, goal_text: str) -> GIESession:
        return GIESession.objects.create(
            user=self.user,
            goal_text=goal_text,
            goal_domain=domain,
            status=GIESession.STATUS_ACTIVE,
            phase=GIESession.PHASE_QUESTION_LOOP,
        )

    def test_schema_fixtures_and_shape_are_stable(self):
        required_shape = {"key", "label", "description", "required", "data_type", "enum_values", "validation"}
        for domain, fixture in GIE_PROMPT_GOLDEN_FIXTURES.items():
            schema = GIEDynamicSchemaService.generate_schema(
                goal_text=fixture["goal_text"],
                intake_analysis={"goal_domain": {"value": domain}},
            )
            replay_schema = GIEDynamicSchemaService.generate_schema(
                goal_text=fixture["goal_text"],
                intake_analysis={"goal_domain": {"value": domain}},
            )

            self.assertEqual(schema, replay_schema)
            self.assertEqual([slot["key"] for slot in schema["required_slots"]], fixture["required_slot_keys"])
            self.assertEqual([slot["key"] for slot in schema["optional_slots"]], fixture["optional_slot_keys"])
            for slot in schema["required_slots"] + schema["optional_slots"]:
                self.assertEqual(set(slot.keys()), required_shape)

    def test_ranking_and_plan_payload_match_golden_rubric(self):
        for domain, fixture in GIE_PROMPT_GOLDEN_FIXTURES.items():
            session = self._build_session(domain=domain, goal_text=fixture["goal_text"])
            slot_states = [
                GIESlotState(
                    session=session,
                    slot_key="timeline_target_date",
                    required=True,
                    status=GIESlotState.STATUS_FILLED,
                    value=fixture["timeline_target_date"],
                    source=GIESlotState.SOURCE_TURN_ANSWER,
                    confidence=1.0,
                ),
                GIESlotState(
                    session=session,
                    slot_key=fixture["capacity_slot_key"],
                    required=True,
                    status=GIESlotState.STATUS_FILLED,
                    value=fixture["capacity_value"],
                    source=GIESlotState.SOURCE_TURN_ANSWER,
                    confidence=1.0,
                ),
            ]
            ranked = GIEHabitRankingService.rank(session=session, slot_states=slot_states, health_profile=None)
            self.assertEqual([item["habit_name"] for item in ranked], fixture["top_habits"])
            for item in ranked:
                self.assertGreaterEqual(len(item["rationale"]), 24)
                self.assertIn(domain, item["rationale"].lower())
                self.assertIn(fixture["timeline_target_date"], item["rationale"])

            plan_payload = GIEPlanningService.build_plan_payload(
                session=session,
                slot_states=[
                    *slot_states,
                    GIESlotState(
                        session=session,
                        slot_key=GIEPlanningService.HABIT_SUGGESTIONS_SLOT_KEY,
                        required=False,
                        status=GIESlotState.STATUS_LOCKED,
                        value=ranked,
                        source=GIESlotState.SOURCE_INFERENCE,
                    ),
                ],
            )
            self.assertEqual(plan_payload["goal_summary"], fixture["goal_text"])
            self.assertGreaterEqual(len(plan_payload["assumptions"]), 2)
            self.assertTrue(any(item.startswith("Habit focus: ") for item in plan_payload["assumptions"]))
            self.assertEqual(plan_payload["milestones"][0]["target_date"], fixture["timeline_target_date"])
            self.assertGreaterEqual(len(plan_payload["milestones"][0]["success_metric"].split()), 5)


class GIERIESignalBuilderTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(email="gie-rie@test.com", password="Password@123")
        self.session = GIESession.objects.create(
            user=self.user,
            goal_text="Build a consistent execution system in 90 days.",
            goal_domain=GIESession.DOMAIN_PERSONAL,
            status=GIESession.STATUS_READY_TO_FINALIZE,
            phase=GIESession.PHASE_REVIEW,
        )

    def test_signal_is_deterministic_and_filters_confirmed_habits(self):
        slot_states = [
            GIESlotState(
                session=self.session,
                slot_key="goal_priority",
                required=False,
                status=GIESlotState.STATUS_FILLED,
                value="high",
                source=GIESlotState.SOURCE_TURN_ANSWER,
            ),
            GIESlotState(
                session=self.session,
                slot_key="weekly_commitment_hours",
                required=True,
                status=GIESlotState.STATUS_FILLED,
                value=14,
                source=GIESlotState.SOURCE_TURN_ANSWER,
            ),
        ]
        ranked = [
            {"habit_name": "A", "rationale": "Reason A"},
            {"habit_name": "B", "rationale": "Reason B"},
            {"habit_name": "C", "rationale": "Reason C"},
        ]
        confirmations = [
            {"habit_name": "A", "decision": "accepted"},
            {"habit_name": "B", "decision": "rejected"},
            {"habit_name": "C", "decision": "accepted"},
        ]

        first = GIEPlanningService.build_rie_signal(
            slot_states=slot_states,
            ranked_habit_suggestions=ranked,
            habit_confirmations=confirmations,
        )
        second = GIEPlanningService.build_rie_signal(
            slot_states=slot_states,
            ranked_habit_suggestions=ranked,
            habit_confirmations=confirmations,
        )

        self.assertEqual(first, second)
        self.assertEqual(first["goal_priority"], "high")
        self.assertEqual(first["suggested_sequence_order"], ["A", "C"])
        self.assertEqual(first["estimated_daily_capacity_minutes"], 120)
        self.assertEqual([item["habit_name"] for item in first["confirmed_habits"]], ["A", "C"])
