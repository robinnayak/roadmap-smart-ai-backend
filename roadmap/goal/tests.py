import shutil
import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIRequestFactory, APITestCase

from authentication.models import CustomUser
from ai.models import AIProcessingJob
from ai.providers.base import AIResponse, BaseAIProvider
from ai.utils.validators import normalize_task_type
from goal.models import Goal, GoalAttributes, GoalCommitmentRecord, Milestone, SubGoal, Task, GoalLink, UserFinancialProfile, FinancialProgressEntry
from goal.serializers import GoalSerializer
from goal.services.goal_domain import build_goal_seed_data, create_goal_for_user
from goal.services.category_resolver import GOAL_CATEGORIES, resolve_category
from goal.services.category_pillars import canonical_to_pillar, pillar_to_default_canonical
from goal.services.contract_template import GoalContractTemplateService
from goal.services.financial_intelligence import build_financial_plan_summary
from goal.services.timeline_ai_provider import (
    TIMELINE_INSIGHT_PROVIDER_OLLAMA,
    OllamaTimelineAIProviderAdapter,
    TimelineAIProviderAdapter,
    get_timeline_ai_provider_adapter,
)
from goal.services.timeline_conflict_detector import detect_goal_conflicts
from goal.services.timeline_insight_service import GoalTimelineInsightService
from goal.services.timeline_overview_insight_service import TimelineOverviewInsightService
from goal.services.timeline_insight_contract import (
    TIMELINE_INSIGHT_TRIGGER_USER_CLICK,
    TimelineInsightBoundaryError,
    assert_no_gie_runtime_dependency,
    assert_read_only_timeline_insight_request,
)
from goal.services.timeline_similar_goal_detector import detect_similar_goals
from goal.views import CreateGoalWithHierarchyAPIView
from routine.models import DailyTaskItem, DailyTaskList


def full_commitment_payload(*, user=None, goal_data=None, **overrides):
    signed_at = overrides.get("signed_at", timezone.now().isoformat())
    payload = {
        "commitment_confirmed": True,
        "commitment_intent": "I am committing to the stated goal outcome.",
        "commitment_effort": "I will protect time and effort for execution.",
        "commitment_responsibility": "I accept full responsibility for following through.",
        "signed_name": "Test User",
        "signed_at": signed_at,
    }
    payload.update(overrides)
    resolved_goal_data = {
        "title": "Contract Goal",
        "description": "Detailed plan description",
        "why_it_matters": ["Long-term growth"],
        "why_do_i_want_this": "I want stronger career optionality.",
        "specific_measurable_target": "Get promoted by Q4 with measurable outcomes.",
        "primary_category": "career",
        "target_date": str(timezone.localdate() + timedelta(days=90)),
    }
    if goal_data:
        resolved_goal_data.update(goal_data)
    resolved_user = user or type(
        "UserStub",
        (),
        {"email": "test-user@example.com", "get_full_name": lambda self: ""},
    )()
    payload["contract_snapshot"] = GoalContractTemplateService().render_snapshot(
        goal_data=resolved_goal_data,
        user=resolved_user,
        signed_name=payload["signed_name"],
        signed_at=payload["signed_at"],
        accepted_gie_commitments=[],
    )
    return payload


class GoalDomainRefactorEndpointTests(APITestCase):
    def setUp(self):
        self.owner = CustomUser.objects.create_user(
            email="goal-domain-owner@test.com",
            password="Password@123",
        )
        self.other_user = CustomUser.objects.create_user(
            email="goal-domain-other@test.com",
            password="Password@123",
        )

    def test_goal_create_endpoint_persists_goal_commitment_record(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            "/goal/",
            data={
                "title": "Service Refactor Goal",
                "description": "Created through endpoint",
                "why_it_matters": ["Consistency"],
                "why_do_i_want_this": "I want a reliable workflow.",
                "specific_measurable_target": "Ship the refactor this quarter.",
                "primary_category": "career",
                "priority": "medium",
                "target_date": str(timezone.localdate() + timedelta(days=30)),
                **full_commitment_payload(),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        goal = Goal.objects.get(user=self.owner, title="Service Refactor Goal")
        record = GoalCommitmentRecord.objects.get(goal=goal)
        self.assertEqual(record.user, self.owner)
        self.assertEqual(record.commitment_intent, "I am committing to the stated goal outcome.")

    def test_goal_hierarchy_endpoint_returns_expected_shape(self):
        goal = Goal.objects.create(
            user=self.owner,
            title="Hierarchy Goal",
            description="Hierarchy payload",
            why_it_matters=["Momentum"],
            primary_category="career",
            status="in_progress",
            start_date=timezone.localdate(),
            target_date=timezone.localdate() + timedelta(days=20),
        )
        milestone = Milestone.objects.create(
            goal=goal,
            title="Milestone 1",
            display_order=1,
            status="in_progress",
        )
        subgoal = SubGoal.objects.create(
            milestone=milestone,
            title="Subgoal 1",
            display_order=1,
            status="in_progress",
        )
        Task.objects.create(
            subgoal=subgoal,
            title="Task 1",
            status="pending",
            priority="medium",
            estimated_duration_minutes=30,
            display_order=1,
        )

        self.client.force_authenticate(self.owner)
        response = self.client.get(f"/goal/goals/{goal.id}/hierarchy/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("goal", response.data)
        self.assertIn("on_track", response.data)
        self.assertIn("milestones", response.data)
        self.assertIn("stats", response.data)
        self.assertEqual(str(response.data["goal"]["id"]), str(goal.id))

    def test_goal_hierarchy_endpoint_returns_404_for_non_owner(self):
        goal = Goal.objects.create(
            user=self.owner,
            title="Private Goal",
            primary_category="career",
            target_date=timezone.localdate() + timedelta(days=10),
        )
        self.client.force_authenticate(self.other_user)
        response = self.client.get(f"/goal/goals/{goal.id}/hierarchy/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class GoalCreateContractValidationTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="goal-create-contract@test.com",
            password="Password@123",
        )
        self.client.force_authenticate(self.user)
        self.base_payload = {
            "title": "Contract Goal",
            "description": "Detailed plan description",
            "why_it_matters": ["Long-term growth"],
            "why_do_i_want_this": "I want stronger career optionality.",
            "specific_measurable_target": "Get promoted by Q4 with measurable outcomes.",
            "primary_category": "career",
            "priority": "medium",
            "target_date": str(timezone.localdate() + timedelta(days=45)),
            **full_commitment_payload(
                user=self.user,
                goal_data={
                    "title": "Contract Goal",
                    "description": "Detailed plan description",
                    "why_it_matters": ["Long-term growth"],
                    "why_do_i_want_this": "I want stronger career optionality.",
                    "specific_measurable_target": "Get promoted by Q4 with measurable outcomes.",
                    "primary_category": "career",
                    "target_date": str(timezone.localdate() + timedelta(days=45)),
                },
            ),
        }

    def test_goal_create_requires_all_contract_fields(self):
        payload = {**self.base_payload}
        payload.pop("description")
        payload["why_it_matters"] = []
        payload["commitment_confirmed"] = False

        response = self.client.post("/goal/", data=payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "validation_error")
        self.assertEqual(response.data["code"], "validation_error")
        details = response.data["details"]
        self.assertIn("description", details)
        self.assertIn("why_it_matters", details)
        self.assertIn("commitment_confirmed", details)

    def test_goal_serializer_normalizes_why_it_matters_string_to_list(self):
        payload = {
            **self.base_payload,
            "why_it_matters": "Security\nFreedom\nSecurity",
        }
        serializer = GoalSerializer(data=payload, context={"request": type("Req", (), {"user": self.user})()})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["why_it_matters"], ["Security", "Freedom"])

    def test_goal_create_with_full_commitment_payload_creates_commitment_record(self):
        response = self.client.post("/goal/", data=self.base_payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        goal = Goal.objects.get(user=self.user, title=self.base_payload["title"])
        record = GoalCommitmentRecord.objects.get(goal=goal)
        self.assertEqual(record.signed_name, self.base_payload["signed_name"])
        self.assertEqual(record.contract_snapshot, self.base_payload["contract_snapshot"])

    def test_goal_create_rejects_missing_commitment_payload_fields(self):
        payload = {**self.base_payload}
        payload.pop("commitment_intent")
        payload["commitment_effort"] = "   "
        payload["signed_at"] = "not-a-datetime"
        payload["contract_snapshot"] = {}

        response = self.client.post("/goal/", data=payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        details = response.data["details"]
        self.assertIn("commitment_intent", details)
        self.assertIn("commitment_effort", details)
        self.assertIn("signed_at", details)
        self.assertIn("contract_snapshot", details)

    def test_create_with_hierarchy_rejects_missing_required_fields_with_stable_contract(self):
        payload = {**self.base_payload}
        payload.pop("specific_measurable_target")
        response = self.client.post("/goal/create-with-hierarchy/", data=payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "validation_error")
        self.assertEqual(response.data["code"], "validation_error")
        self.assertEqual(
            response.data["message"],
            "specific_measurable_target: Specific measurable target is required.",
        )
        self.assertIn("specific_measurable_target", response.data["details"])

    def test_create_with_hierarchy_rejects_missing_commitment_payload_fields(self):
        payload = {**self.base_payload}
        payload.pop("commitment_responsibility")
        payload["signed_at"] = "bad-datetime"
        payload["contract_snapshot"] = {}
        response = self.client.post("/goal/create-with-hierarchy/", data=payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("commitment_responsibility", response.data["details"])
        self.assertIn("signed_at", response.data["details"])
        self.assertIn("contract_snapshot", response.data["details"])

    def test_create_with_hierarchy_full_commitment_payload_creates_commitment_record(self):
        response = self.client.post("/goal/create-with-hierarchy/", data=self.base_payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        goal = Goal.objects.get(user=self.user, title=self.base_payload["title"])
        record = GoalCommitmentRecord.objects.get(goal=goal)
        self.assertEqual(record.user, self.user)
        self.assertEqual(record.contract_snapshot, self.base_payload["contract_snapshot"])

    def test_create_with_hierarchy_allows_target_dates_shorter_than_30_days(self):
        payload = {
            **self.base_payload,
            "target_date": str(timezone.localdate() + timedelta(days=14)),
        }

        response = self.client.post("/goal/create-with-hierarchy/", data=payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

    def test_create_with_hierarchy_rejects_target_dates_beyond_two_months(self):
        payload = {
            **self.base_payload,
            "target_date": str(timezone.localdate() + timedelta(days=70)),
        }

        response = self.client.post("/goal/create-with-hierarchy/", data=payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("target_date", response.data["details"])
        self.assertIn("within 2 months", response.data["message"])

    @patch("goal.serializers.GoalCommitmentRecord.objects.create")
    def test_goal_create_rolls_back_when_commitment_record_creation_fails(self, mock_commitment_create):
        mock_commitment_create.side_effect = RuntimeError("commitment record create failed")

        response = self.client.post("/goal/", data=self.base_payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertFalse(Goal.objects.filter(user=self.user, title=self.base_payload["title"]).exists())
        self.assertEqual(GoalCommitmentRecord.objects.count(), 0)

    def test_goal_commitment_record_signed_fields_are_immutable(self):
        response = self.client.post("/goal/", data=self.base_payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        goal = Goal.objects.get(user=self.user, title=self.base_payload["title"])
        record = GoalCommitmentRecord.objects.get(goal=goal)
        record.signed_name = "Modified Name"

        with self.assertRaises(ValidationError):
            record.save()

    def test_build_goal_seed_data_contains_required_generation_context(self):
        goal = Goal.objects.create(
            user=self.user,
            title="Seed Data Goal",
            description="Seed description",
            why_it_matters=["Relevance", "Impact"],
            primary_category="career",
            priority="high",
            target_date=timezone.localdate() + timedelta(days=120),
            impact_dimensions={
                "why_do_i_want_this": "Personal growth",
                "specific_measurable_target": "Lead two projects by Q4",
            },
        )
        payload = build_goal_seed_data(goal)
        self.assertEqual(payload["priority"], "high")
        self.assertEqual(payload["why_do_i_want_this"], "Personal growth")
        self.assertEqual(payload["specific_measurable_target"], "Lead two projects by Q4")
        self.assertEqual(payload["why_it_matters"], ["Relevance", "Impact"])

    @patch("ai.services.text_extraction.GoalAttributeExtractor.extract_goal_attributes")
    def test_extract_and_save_attributes_stores_inner_payload_in_financial_field(self, mock_extract):
        goal = Goal.objects.create(
            user=self.user,
            title="Emergency Fund",
            primary_category="finance",
            target_date=timezone.localdate() + timedelta(days=90),
        )
        mock_extract.return_value = {
            "status": "success",
            "data": {
                "financial_data": {
                    "target_amount": 500000,
                    "current_amount": 100000,
                }
            },
        }

        serializer = GoalSerializer(context={"request": type("Req", (), {"user": self.user})()})
        saved = serializer._extract_and_save_attributes(goal, "Save 500000", self.user)

        self.assertTrue(saved)
        goal.refresh_from_db()
        self.assertEqual(
            goal.attributes.financial_data,
            {
                "target_amount": 500000,
                "current_amount": 100000,
            },
        )
        self.assertIsNone(goal.attributes.personal_data)
        self.assertIsNone(goal.attributes.career_data)
        self.assertIsNone(goal.attributes.health_data)

    def test_goal_save_without_goal_attributes_input_does_not_create_placeholder_attributes(self):
        goal = Goal.objects.create(
            user=self.user,
            title="No Attribute Signal Goal",
            primary_category="career",
            target_date=timezone.localdate() + timedelta(days=30),
        )

        self.assertFalse(GoalAttributes.objects.filter(goal=goal).exists())


class GoalContractTemplateServiceTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="goal-contract-template@test.com",
            password="Password@123",
            first_name="Template",
            last_name="Tester",
        )
        self.service = GoalContractTemplateService()

    def test_render_snapshot_supports_all_goal_categories(self):
        categories = [
            "business",
            "fitness",
            "learning",
            "wellness",
            "creative",
            "nutrition",
            "productivity",
            "travel",
            "digital_habits",
            "spiritual",
            "relationships",
            "education",
            "career",
            "finance",
            "communication",
        ]

        for category in categories:
            snapshot = self.service.render_snapshot(
                goal_data={
                    "id": "goal-1",
                    "title": f"{category.title()} Goal",
                    "description": f"{category} description",
                    "primary_category": category,
                    "why_it_matters": [f"{category} growth"],
                    "why_do_i_want_this": f"I want stronger {category} outcomes.",
                    "specific_measurable_target": f"Reach my {category} milestone.",
                    "target_date": str(timezone.localdate() + timedelta(days=60)),
                },
                user=self.user,
                signed_name="Template Tester",
                signed_at=timezone.now().isoformat(),
            )
            self.assertEqual(snapshot["version"], "wave2.v1")
            self.assertEqual(snapshot["category"], category)
            self.assertTrue(snapshot["sections"]["i_will"])
            self.assertTrue(snapshot["sections"]["i_will_not"])
            self.assertTrue(snapshot["sections"]["reality_anchors"])
            self.assertTrue(snapshot["sections"]["quit_anchors"])

    def test_render_snapshot_populates_dynamic_fields_and_gie_commitments(self):
        snapshot = self.service.render_snapshot(
            goal_data={
                "id": "goal-2",
                "title": "Save for a house deposit",
                "description": "Build the savings base deliberately.",
                "primary_category": "finance",
                "why_it_matters": ["family security", "stability"],
                "why_do_i_want_this": "I want to reduce housing stress.",
                "specific_measurable_target": "Save 500000 by year end.",
                "financial_target_amount": "500000.00",
                "target_date": str(timezone.localdate() + timedelta(days=120)),
            },
            user=self.user,
            signed_name="Template Tester",
            signed_at=timezone.now().isoformat(),
            accepted_gie_commitments=[
                {
                    "id": "c1",
                    "title": "Monthly transfer",
                    "statement": "I commit to transferring money at the start of each month.",
                    "linked_milestone_title": "Milestone 1",
                }
            ],
        )
        self.assertEqual(snapshot["goal_id"], "goal-2")
        self.assertEqual(snapshot["header"]["user_display_name"], "Template Tester")
        self.assertEqual(snapshot["gie_commitments"][0]["id"], "c1")
        self.assertIn("Save 500000 by year end.", " ".join(snapshot["sections"]["i_will"]))
        self.assertIn("500000.00", " ".join(snapshot["sections"]["quit_anchors"]))

    def test_render_snapshot_falls_back_deterministically_when_optional_fields_missing(self):
        snapshot = self.service.render_snapshot(
            goal_data={
                "title": "Basic Goal",
                "description": "",
                "primary_category": "productivity",
                "why_it_matters": [],
                "why_do_i_want_this": "",
                "specific_measurable_target": "",
            },
            user=self.user,
            signed_name="Template Tester",
            signed_at=timezone.now().isoformat(),
        )
        self.assertTrue(snapshot["sections"]["i_will"])
        self.assertTrue(snapshot["sections"]["quit_anchors"])
        self.assertEqual(snapshot["gie_commitments"], [])


class GoalDetailEndpointTests(APITestCase):
    def setUp(self):
        self.owner = CustomUser.objects.create_user(
            email="goal-detail-owner@test.com",
            password="Password@123",
        )
        self.other_user = CustomUser.objects.create_user(
            email="goal-detail-other@test.com",
            password="Password@123",
        )
        self.goal = Goal.objects.create(
            user=self.owner,
            title="Owner Goal",
            description="Initial description",
            why_it_matters=["Growth"],
            primary_category="career",
            priority="medium",
            status="in_progress",
            start_date=timezone.localdate(),
            target_date=timezone.localdate() + timedelta(days=45),
        )
        self.url = f"/goal/goals/{self.goal.id}/"

    def test_owner_get_goal_succeeds(self):
        self.client.force_authenticate(self.owner)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(str(response.data["goal"]["id"]), str(self.goal.id))

    def test_non_owner_get_goal_returns_404(self):
        self.client.force_authenticate(self.other_user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_owner_patch_goal_succeeds(self):
        self.client.force_authenticate(self.owner)
        response = self.client.patch(
            self.url,
            data={"title": "Updated Goal Title"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.goal.refresh_from_db()
        self.assertEqual(self.goal.title, "Updated Goal Title")


class GoalCommitmentContractEndpointTests(APITestCase):
    def setUp(self):
        self.owner = CustomUser.objects.create_user(
            email="goal-contract-owner@test.com",
            password="Password@123",
        )
        self.other_user = CustomUser.objects.create_user(
            email="goal-contract-other@test.com",
            password="Password@123",
        )
        self.goal = Goal.objects.create(
            user=self.owner,
            title="Owner Contract Goal",
            description="Initial description",
            why_it_matters=["Growth"],
            primary_category="career",
            priority="medium",
            status="in_progress",
            start_date=timezone.localdate(),
            target_date=timezone.localdate() + timedelta(days=45),
        )
        commitment_payload = full_commitment_payload(
            user=self.owner,
            goal_data={
                "id": str(self.goal.id),
                "title": self.goal.title,
                "description": self.goal.description,
                "primary_category": self.goal.primary_category,
                "why_it_matters": self.goal.why_it_matters,
                "target_date": str(self.goal.target_date),
            },
        )
        self.record = GoalCommitmentRecord.objects.create(
            goal=self.goal,
            user=self.owner,
            commitment_intent=commitment_payload["commitment_intent"],
            commitment_effort=commitment_payload["commitment_effort"],
            commitment_responsibility=commitment_payload["commitment_responsibility"],
            signed_name=commitment_payload["signed_name"],
            signed_at=timezone.datetime.fromisoformat(commitment_payload["signed_at"].replace("Z", "+00:00")),
            contract_snapshot=commitment_payload["contract_snapshot"],
        )
        self.url = f"/goal/goals/{self.goal.id}/commitment-contract/"

    def test_owner_get_goal_commitment_contract_returns_persisted_snapshot(self):
        self.client.force_authenticate(self.owner)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["goal_id"], str(self.goal.id))
        self.assertEqual(response.data["contract_snapshot"], self.record.contract_snapshot)

    def test_non_owner_get_goal_commitment_contract_returns_404(self):
        self.client.force_authenticate(self.other_user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_missing_goal_commitment_record_returns_fallback_snapshot(self):
        self.record.delete()
        self.client.force_authenticate(self.owner)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["goal_id"], str(self.goal.id))
        self.assertIn("contract_snapshot", response.data)
        self.assertEqual(response.data["contract_snapshot"]["title"], self.goal.title)

    def test_owner_put_goal_succeeds(self):
        self.client.force_authenticate(self.owner)
        response = self.client.put(
            self.url,
            data={
                "title": "PUT Goal Title",
                "description": "Updated description via put",
                "why_it_matters": ["Ownership", "Consistency"],
                "primary_category": "career",
                "impact_dimensions": {},
                "priority": "high",
                "status": "in_progress",
                "start_date": str(self.goal.start_date),
                "target_date": str(self.goal.target_date),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.goal.refresh_from_db()
        self.assertEqual(self.goal.title, "PUT Goal Title")
        self.assertEqual(self.goal.priority, "high")

    def test_non_owner_delete_goal_returns_404(self):
        self.client.force_authenticate(self.other_user)
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_owner_delete_goal_succeeds(self):
        self.client.force_authenticate(self.owner)
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Goal.objects.filter(id=self.goal.id).exists())


class TaskDetailOwnershipTests(APITestCase):
    def setUp(self):
        self.owner = CustomUser.objects.create_user(
            email="goal-owner@test.com",
            password="Password@123",
        )
        self.other_user = CustomUser.objects.create_user(
            email="goal-other@test.com",
            password="Password@123",
        )
        goal = Goal.objects.create(
            user=self.owner,
            title="Owner Goal",
            primary_category="career",
            status="in_progress",
            target_date=timezone.localdate() + timedelta(days=30),
        )
        milestone = Milestone.objects.create(
            goal=goal,
            title="Owner Milestone",
            display_order=1,
            status="in_progress",
        )
        subgoal = SubGoal.objects.create(
            milestone=milestone,
            title="Owner Subgoal",
            display_order=1,
            status="in_progress",
        )
        self.task = Task.objects.create(
            subgoal=subgoal,
            title="Owner Task",
            status="pending",
            priority="medium",
            estimated_duration_minutes=45,
            display_order=1,
        )
        self.url = f"/goal/tasks/{self.task.id}/"

    def test_non_owner_get_task_returns_404(self):
        self.client.force_authenticate(self.other_user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_non_owner_put_task_returns_404(self):
        self.client.force_authenticate(self.other_user)
        response = self.client.put(self.url, data={"title": "Hacked"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_non_owner_delete_task_returns_404(self):
        self.client.force_authenticate(self.other_user)
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_owner_get_task_succeeds(self):
        self.client.force_authenticate(self.owner)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(str(response.data["id"]), str(self.task.id))

    def test_owner_put_allows_status_transitions_and_cascades_hierarchy(self):
        self.client.force_authenticate(self.owner)

        complete_response = self.client.put(
            self.url,
            data={"status": "completed"},
            format="json",
        )
        self.assertEqual(complete_response.status_code, status.HTTP_200_OK)

        self.task.refresh_from_db()
        subgoal = self.task.subgoal
        milestone = subgoal.milestone
        goal = milestone.goal
        subgoal.refresh_from_db()
        milestone.refresh_from_db()
        goal.refresh_from_db()

        self.assertEqual(self.task.status, "completed")
        self.assertIsNotNone(self.task.completed_at)
        self.assertEqual(subgoal.status, "completed")
        self.assertEqual(milestone.status, "completed")
        self.assertEqual(goal.status, "completed")

        revert_response = self.client.put(
            self.url,
            data={"status": "skipped"},
            format="json",
        )
        self.assertEqual(revert_response.status_code, status.HTTP_200_OK)

        self.task.refresh_from_db()
        subgoal.refresh_from_db()
        milestone.refresh_from_db()
        goal.refresh_from_db()

        self.assertEqual(self.task.status, "skipped")
        self.assertIsNone(self.task.completed_at)
        self.assertEqual(subgoal.status, "pending")
        self.assertEqual(milestone.status, "not_started")
        self.assertEqual(goal.status, "not_started")

    def test_owner_put_rejects_invalid_status(self):
        self.client.force_authenticate(self.owner)
        response = self.client.put(
            self.url,
            data={"status": "archived"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("status", response.data)


class GoalHierarchyMutationIntegrationTests(APITestCase):
    def setUp(self):
        self.owner = CustomUser.objects.create_user(
            email="goal-hierarchy-owner@test.com",
            password="Password@123",
        )
        self.other_user = CustomUser.objects.create_user(
            email="goal-hierarchy-other@test.com",
            password="Password@123",
        )
        self.goal = Goal.objects.create(
            user=self.owner,
            title="Hierarchy Mutation Goal",
            primary_category="career",
            status="not_started",
            target_date=timezone.localdate() + timedelta(days=30),
        )
        self.milestone = Milestone.objects.create(
            goal=self.goal,
            title="Hierarchy Mutation Milestone",
            display_order=1,
            status="not_started",
        )
        self.subgoal = SubGoal.objects.create(
            milestone=self.milestone,
            title="Hierarchy Mutation SubGoal",
            display_order=1,
            status="pending",
        )
        self.task_one = Task.objects.create(
            subgoal=self.subgoal,
            title="Hierarchy Task One",
            status="pending",
            priority="medium",
            estimated_duration_minutes=30,
            display_order=1,
        )
        self.task_two = Task.objects.create(
            subgoal=self.subgoal,
            title="Hierarchy Task Two",
            status="pending",
            priority="medium",
            estimated_duration_minutes=30,
            display_order=2,
        )
        self.task_one_url = f"/goal/tasks/{self.task_one.id}/"
        self.task_two_url = f"/goal/tasks/{self.task_two.id}/"
        self.hierarchy_url = f"/goal/goals/{self.goal.id}/hierarchy/"

    def _assert_hierarchy_state(
        self,
        expected_subgoal_status,
        expected_subgoal_progress,
        expected_milestone_status,
        expected_milestone_progress,
        expected_goal_status,
        expected_goal_progress,
    ):
        self.subgoal.refresh_from_db()
        self.milestone.refresh_from_db()
        self.goal.refresh_from_db()

        self.assertEqual(self.subgoal.status, expected_subgoal_status)
        self.assertEqual(self.subgoal.progress_percentage, expected_subgoal_progress)
        self.assertEqual(self.milestone.status, expected_milestone_status)
        self.assertEqual(self.milestone.progress_percentage, expected_milestone_progress)
        self.assertEqual(self.goal.status, expected_goal_status)
        self.assertEqual(self.goal.progress_percentage, expected_goal_progress)

    def test_end_to_end_task_mutation_propagates_and_reverts_hierarchy_progress(self):
        self.client.force_authenticate(self.owner)

        task_one_complete = self.client.put(
            self.task_one_url,
            data={"status": "completed"},
            format="json",
        )
        self.assertEqual(task_one_complete.status_code, status.HTTP_200_OK)
        self.task_one.refresh_from_db()
        self.assertEqual(self.task_one.status, "completed")
        self.assertIsNotNone(self.task_one.completed_at)
        self._assert_hierarchy_state(
            expected_subgoal_status="in_progress",
            expected_subgoal_progress=50,
            expected_milestone_status="in_progress",
            expected_milestone_progress=50,
            expected_goal_status="in_progress",
            expected_goal_progress=50,
        )

        task_two_complete = self.client.put(
            self.task_two_url,
            data={"status": "completed"},
            format="json",
        )
        self.assertEqual(task_two_complete.status_code, status.HTTP_200_OK)
        self.task_two.refresh_from_db()
        self.assertEqual(self.task_two.status, "completed")
        self.assertIsNotNone(self.task_two.completed_at)
        self._assert_hierarchy_state(
            expected_subgoal_status="completed",
            expected_subgoal_progress=100,
            expected_milestone_status="completed",
            expected_milestone_progress=100,
            expected_goal_status="completed",
            expected_goal_progress=100,
        )
        self.assertIsNotNone(self.subgoal.completed_date)
        self.assertIsNotNone(self.milestone.completed_date)

        task_one_revert_to_skipped = self.client.put(
            self.task_one_url,
            data={"status": "skipped"},
            format="json",
        )
        self.assertEqual(task_one_revert_to_skipped.status_code, status.HTTP_200_OK)
        self.task_one.refresh_from_db()
        self.assertEqual(self.task_one.status, "skipped")
        self.assertIsNone(self.task_one.completed_at)
        self._assert_hierarchy_state(
            expected_subgoal_status="in_progress",
            expected_subgoal_progress=50,
            expected_milestone_status="in_progress",
            expected_milestone_progress=50,
            expected_goal_status="in_progress",
            expected_goal_progress=50,
        )
        self.assertIsNone(self.subgoal.completed_date)
        self.assertIsNone(self.milestone.completed_date)

        task_two_revert_to_pending = self.client.put(
            self.task_two_url,
            data={"status": "pending"},
            format="json",
        )
        self.assertEqual(task_two_revert_to_pending.status_code, status.HTTP_200_OK)
        self.task_two.refresh_from_db()
        self.assertEqual(self.task_two.status, "pending")
        self.assertIsNone(self.task_two.completed_at)
        self._assert_hierarchy_state(
            expected_subgoal_status="pending",
            expected_subgoal_progress=0,
            expected_milestone_status="not_started",
            expected_milestone_progress=0,
            expected_goal_status="in_progress",
            expected_goal_progress=0,
        )
        self.assertIsNone(self.subgoal.completed_date)
        self.assertIsNone(self.milestone.completed_date)

    def test_owner_can_retrieve_and_mutate_while_non_owner_receives_404(self):
        self.client.force_authenticate(self.owner)

        owner_task_get = self.client.get(self.task_one_url)
        self.assertEqual(owner_task_get.status_code, status.HTTP_200_OK)
        owner_hierarchy_get = self.client.get(self.hierarchy_url)
        self.assertEqual(owner_hierarchy_get.status_code, status.HTTP_200_OK)

        owner_mutation = self.client.put(
            self.task_one_url,
            data={"status": "completed"},
            format="json",
        )
        self.assertEqual(owner_mutation.status_code, status.HTTP_200_OK)

        self.client.force_authenticate(self.other_user)

        non_owner_task_get = self.client.get(self.task_one_url)
        self.assertEqual(non_owner_task_get.status_code, status.HTTP_404_NOT_FOUND)
        non_owner_hierarchy_get = self.client.get(self.hierarchy_url)
        self.assertEqual(non_owner_hierarchy_get.status_code, status.HTTP_404_NOT_FOUND)
        non_owner_mutation = self.client.put(
            self.task_one_url,
            data={"status": "completed"},
            format="json",
        )
        self.assertEqual(non_owner_mutation.status_code, status.HTTP_404_NOT_FOUND)


class CreateGoalWithHierarchyConfigFallbackTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="goal-hierarchy-config@test.com",
            password="Password@123",
        )
        self.client.force_authenticate(self.user)
        self.payload = {
            "title": "Config fallback goal",
            "description": "Should create goal even when AI env is missing",
            "why_it_matters": ["Reliability"],
            "why_do_i_want_this": "I want dependable goal setup.",
            "specific_measurable_target": "Create the goal without runtime AI configured.",
            "primary_category": "career",
            "priority": "medium",
            "target_date": str(timezone.localdate() + timedelta(days=45)),
            **full_commitment_payload(),
            "goal_attributes_input": "Learn machine learning fundamentals in 60 days",
        }

    @patch("goal.services.create_contract.list_missing_commitment_fields", return_value=["wave1_bypass_for_existing_async_tests"])
    @patch("goal.views.build_ai_runtime_error_message", return_value="AI runtime is not configured. Missing environment variable(s): OLLAMA_HOST. Set them in backend environment and restart the server.")
    @patch("goal.views.get_missing_ai_env_vars", return_value=["OLLAMA_HOST"])
    def test_async_create_returns_failed_job_when_ai_runtime_not_configured(
        self,
        _mocked_commitment_bypass,
        _mock_missing_ai_env,
        _mock_error_message,
    ):
        with patch.dict("os.environ", {"OLLAMA_MODEL": "", "OLLAMA_HOST": ""}, clear=False):
            response = self.client.post(
                "/goal/create-with-hierarchy/",
                data=self.payload,
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertIn("goal", response.data)
        self.assertIn("job", response.data)
        self.assertEqual(response.data["job"]["status"], "failed")
        self.assertIn("AI runtime is not configured", response.data["job"]["error_message"])

        job_id = response.data["job"]["id"]
        job = AIProcessingJob.objects.get(id=job_id, user=self.user)
        self.assertEqual(job.status, "failed")
        self.assertIn("Missing environment variable(s): OLLAMA_HOST", job.error_message)

    @patch("goal.services.create_contract.list_missing_commitment_fields", return_value=["wave1_bypass_for_existing_async_tests"])
    @patch("goal.views.build_ai_runtime_error_message", return_value="AI runtime is not configured. Missing environment variable(s): OLLAMA_HOST. Set them in backend environment and restart the server.")
    @patch("goal.views.get_missing_ai_env_vars", return_value=["OLLAMA_HOST"])
    def test_sync_create_returns_created_goal_with_hierarchy_unavailable_message(
        self,
        _mocked_commitment_bypass,
        _mock_missing_ai_env,
        _mock_error_message,
    ):
        with patch.dict("os.environ", {"OLLAMA_MODEL": "", "OLLAMA_HOST": ""}, clear=False):
            response = self.client.post(
                "/goal/create-with-hierarchy/?sync=true",
                data=self.payload,
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("goal", response.data)
        self.assertIn("hierarchy generation is unavailable", response.data["message"].lower())
        self.assertIn("AI runtime is not configured", response.data["error"])


class CreateGoalWithHierarchyAsyncCommitSafetyTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="goal-hierarchy-commit-safety@test.com",
            password="Password@123",
        )
        self.client.force_authenticate(self.user)
        self.payload = {
            "title": "Commit safety goal",
            "description": "Verify async worker starts after commit",
            "why_it_matters": ["Race prevention"],
            "why_do_i_want_this": "Avoid intermittent hierarchy failures after finalize.",
            "specific_measurable_target": "Finalize and generate hierarchy reliably.",
            "primary_category": "career",
            "priority": "medium",
            "target_date": str(timezone.localdate() + timedelta(days=45)),
            **full_commitment_payload(),
        }

    @patch("goal.views.get_missing_ai_env_vars", return_value=[])
    @patch("goal.views.threading.Thread")
    @patch("goal.services.create_contract.list_missing_commitment_fields", return_value=["wave1_bypass_for_existing_async_tests"])
    def test_async_worker_starts_only_after_transaction_commit(
        self,
        _mocked_commitment_bypass,
        mocked_thread,
        _mocked_missing_env,
    ):
        with transaction.atomic():
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                response = self.client.post(
                    "/goal/create-with-hierarchy/",
                    data=self.payload,
                    format="json",
                )
            self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
            mocked_thread.return_value.start.assert_not_called()
            self.assertEqual(len(callbacks), 1)
            callbacks[0]()
            mocked_thread.return_value.start.assert_called_once()

    @patch.object(CreateGoalWithHierarchyAPIView, "_save_complete_hierarchy_to_db")
    @patch("goal.views.GoalHierarchyGenerator")
    def test_async_worker_marks_job_completed_only_after_hierarchy_is_saved(
        self,
        mock_generator_cls,
        mock_save_hierarchy,
    ):
        goal = Goal.objects.create(
            user=self.user,
            title="Async Save Goal",
            description="Verify completion happens after persistence.",
            why_it_matters=["Reliability"],
            primary_category="career",
            priority="medium",
            target_date=timezone.localdate() + timedelta(days=45),
        )
        job = AIProcessingJob.objects.create(
            user=self.user,
            job_type="milestone_generation",
            input_data={},
            metadata={},
            status="pending",
            progress_percentage=0,
        )

        mock_generator = mock_generator_cls.return_value
        mock_generator.provider.model = "test-model"
        mock_generator.generate_complete_hierarchy.return_value = {
            "status": "success",
            "data": {
                "milestones": [
                    {
                        "milestone_data": {"title": "Month 1"},
                        "subgoals": [],
                    }
                ],
                "stats": {"milestones_total": 1, "subgoals_total": 0, "tasks_total": 0},
            },
        }
        mock_save_hierarchy.return_value = {"milestones": 1, "subgoals": 0, "tasks": 0}

        view = CreateGoalWithHierarchyAPIView()
        view._run_hierarchy_generation_async(str(goal.id), self.user.id, str(job.id))

        mock_generator.generate_complete_hierarchy.assert_called_once()
        self.assertFalse(mock_generator.generate_complete_hierarchy.call_args.kwargs["mark_job_completed"])

        job.refresh_from_db()
        self.assertEqual(job.status, "completed")
        self.assertEqual(job.output_data["saved_counts"]["milestones"], 1)

    @patch.object(CreateGoalWithHierarchyAPIView, "_save_complete_hierarchy_to_db")
    @patch("goal.views.GoalHierarchyGenerator")
    def test_async_worker_marks_job_failed_when_generated_hierarchy_saves_nothing(
        self,
        mock_generator_cls,
        mock_save_hierarchy,
    ):
        goal = Goal.objects.create(
            user=self.user,
            title="Async Failure Goal",
            description="Verify failed save does not look complete.",
            why_it_matters=["Integrity"],
            primary_category="career",
            priority="medium",
            target_date=timezone.localdate() + timedelta(days=45),
        )
        job = AIProcessingJob.objects.create(
            user=self.user,
            job_type="milestone_generation",
            input_data={},
            metadata={},
            status="pending",
            progress_percentage=0,
        )

        mock_generator = mock_generator_cls.return_value
        mock_generator.provider.model = "test-model"
        mock_generator.generate_complete_hierarchy.return_value = {
            "status": "success",
            "data": {
                "milestones": [
                    {
                        "milestone_data": {"title": "Month 1"},
                        "subgoals": [],
                    }
                ],
                "stats": {"milestones_total": 1, "subgoals_total": 0, "tasks_total": 0},
            },
        }
        mock_save_hierarchy.return_value = {"milestones": 0, "subgoals": 0, "tasks": 0}

        view = CreateGoalWithHierarchyAPIView()
        view._run_hierarchy_generation_async(str(goal.id), self.user.id, str(job.id))

        job.refresh_from_db()
        self.assertEqual(job.status, "failed")
        self.assertIn("failed to save any milestones", job.error_message.lower())


class FinancialProfileAPIViewTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="financial-profile-owner@test.com",
            password="Password@123",
        )
        self.other_user = CustomUser.objects.create_user(
            email="financial-profile-other@test.com",
            password="Password@123",
        )
        self.url = "/goal/financial-profile/"

    def _profile_payload(self):
        return {
            "employment_type": "salaried_employee",
            "monthly_income_range": "50k_1l",
            "monthly_surplus_range": "10k_30k",
            "primary_skill_area": "technology",
            "total_current_savings_range": "under_5l",
        }

    def test_get_returns_exists_false_when_profile_absent(self):
        self.client.force_authenticate(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["exists"], False)
        self.assertIsNone(response.data["profile"])
        self.assertEqual(response.data["needs_profile_review"], False)

    def test_post_creates_profile_with_contract_shape(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(self.url, data=self._profile_payload(), format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("profile", response.data)
        self.assertEqual(response.data["profile"]["employment_type"], "salaried_employee")
        self.assertEqual(response.data["needs_profile_review"], False)

    def test_post_invalid_enum_returns_contract_error_shape(self):
        self.client.force_authenticate(self.user)
        payload = self._profile_payload()
        payload["employment_type"] = "invalid_value"
        response = self.client.post(self.url, data=payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "validation_error")
        self.assertIn("employment_type", response.data["details"])

    def test_patch_profile_content_update_clears_review_state(self):
        profile = UserFinancialProfile.objects.create(
            user=self.user,
            employment_type="salaried_employee",
            monthly_income_range="50k_1l",
            monthly_surplus_range="10k_30k",
            primary_skill_area="technology",
            total_current_savings_range="under_5l",
            needs_review=True,
            review_reason="Outdated assumptions",
        )
        self.client.force_authenticate(self.user)
        response = self.client.patch(
            self.url,
            data={"monthly_surplus_range": "30k_70k"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        profile.refresh_from_db()
        self.assertEqual(profile.monthly_surplus_range, "30k_70k")
        self.assertEqual(profile.needs_review, False)
        self.assertEqual(profile.review_reason, "")
        self.assertEqual(response.data["needs_profile_review"], False)

    def test_linked_career_completion_sets_needs_profile_review(self):
        profile = UserFinancialProfile.objects.create(
            user=self.user,
            employment_type="salaried_employee",
            monthly_income_range="50k_1l",
            monthly_surplus_range="10k_30k",
            primary_skill_area="technology",
            total_current_savings_range="under_5l",
            needs_review=False,
            review_reason="",
        )
        source_goal = Goal.objects.create(
            user=self.user,
            title="Buy apartment",
            primary_category="financial",
            target_date=timezone.localdate() + timedelta(days=365),
        )
        contributing_goal = Goal.objects.create(
            user=self.user,
            title="Get promoted",
            primary_category="career",
            status="in_progress",
            target_date=timezone.localdate() + timedelta(days=120),
        )
        GoalLink.objects.create(source_goal=source_goal, contributing_goal=contributing_goal)

        self.client.force_authenticate(self.user)
        goal_update = self.client.patch(
            f"/goal/goals/{contributing_goal.id}/",
            data={"status": "completed"},
            format="json",
        )
        self.assertEqual(goal_update.status_code, status.HTTP_200_OK)

        profile.refresh_from_db()
        self.assertEqual(profile.needs_review, True)
        self.assertIn("linked career goal", profile.review_reason.lower())

        profile_view = self.client.get(self.url)
        self.assertEqual(profile_view.status_code, status.HTTP_200_OK)
        self.assertEqual(profile_view.data["exists"], True)
        self.assertEqual(profile_view.data["needs_profile_review"], True)

    def test_linked_contributing_goal_paused_sets_needs_profile_review(self):
        profile = UserFinancialProfile.objects.create(
            user=self.user,
            employment_type="salaried_employee",
            monthly_income_range="50k_1l",
            monthly_surplus_range="10k_30k",
            primary_skill_area="technology",
            total_current_savings_range="under_5l",
            needs_review=False,
            review_reason="",
        )
        source_goal = Goal.objects.create(
            user=self.user,
            title="Emergency fund",
            primary_category="financial",
            target_date=timezone.localdate() + timedelta(days=365),
        )
        contributing_goal = Goal.objects.create(
            user=self.user,
            title="Freelance growth",
            primary_category="personal",
            status="in_progress",
            target_date=timezone.localdate() + timedelta(days=120),
        )
        GoalLink.objects.create(source_goal=source_goal, contributing_goal=contributing_goal)

        self.client.force_authenticate(self.user)
        goal_update = self.client.patch(
            f"/goal/goals/{contributing_goal.id}/",
            data={"status": "paused"},
            format="json",
        )
        self.assertEqual(goal_update.status_code, status.HTTP_200_OK)

        profile.refresh_from_db()
        self.assertEqual(profile.needs_review, True)
        self.assertIn("paused/cancelled", profile.review_reason.lower())


class GoalLinkAPIViewTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="goal-link-owner@test.com",
            password="Password@123",
        )
        self.other_user = CustomUser.objects.create_user(
            email="goal-link-other@test.com",
            password="Password@123",
        )
        self.financial_goal = Goal.objects.create(
            user=self.user,
            title="Buy apartment",
            primary_category="financial",
            target_date=timezone.localdate() + timedelta(days=365),
        )
        self.career_goal = Goal.objects.create(
            user=self.user,
            title="Get promoted",
            primary_category="career",
            target_date=timezone.localdate() + timedelta(days=180),
        )
        self.personal_goal = Goal.objects.create(
            user=self.user,
            title="Improve communication",
            primary_category="personal",
            target_date=timezone.localdate() + timedelta(days=180),
        )
        self.health_goal = Goal.objects.create(
            user=self.user,
            title="Lose fat",
            primary_category="health",
            target_date=timezone.localdate() + timedelta(days=120),
        )
        self.other_users_goal = Goal.objects.create(
            user=self.other_user,
            title="Other user's career",
            primary_category="career",
            target_date=timezone.localdate() + timedelta(days=200),
        )
        self.links_url = f"/goal/goals/{self.financial_goal.id}/links/"

    def test_create_link_succeeds_for_financial_to_career_or_personal(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            self.links_url,
            data={
                "contributing_goal": str(self.career_goal.id),
                "link_type": "income_growth",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(str(response.data["source_goal"]), str(self.financial_goal.id))
        self.assertEqual(str(response.data["contributing_goal"]), str(self.career_goal.id))

    def test_create_link_rejects_non_financial_source(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            f"/goal/goals/{self.career_goal.id}/links/",
            data={
                "contributing_goal": str(self.personal_goal.id),
                "link_type": "skill_building",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "validation_error")

    def test_create_link_rejects_invalid_contributing_category(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            self.links_url,
            data={
                "contributing_goal": str(self.health_goal.id),
                "link_type": "lifestyle",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "validation_error")

    def test_create_link_rejects_cross_user_goal(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            self.links_url,
            data={
                "contributing_goal": str(self.other_users_goal.id),
                "link_type": "income_growth",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "validation_error")

    def test_create_link_rejects_duplicates(self):
        GoalLink.objects.create(
            source_goal=self.financial_goal,
            contributing_goal=self.career_goal,
            link_type="income_growth",
        )
        self.client.force_authenticate(self.user)
        response = self.client.post(
            self.links_url,
            data={
                "contributing_goal": str(self.career_goal.id),
                "link_type": "income_growth",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "validation_error")
        self.assertIn("link", response.data["details"])

    def test_list_links_returns_source_links(self):
        GoalLink.objects.create(
            source_goal=self.financial_goal,
            contributing_goal=self.career_goal,
            link_type="income_growth",
        )
        GoalLink.objects.create(
            source_goal=self.financial_goal,
            contributing_goal=self.personal_goal,
            link_type="skill_building",
        )
        self.client.force_authenticate(self.user)
        response = self.client.get(self.links_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["source_goal_id"], str(self.financial_goal.id))
        self.assertEqual(len(response.data["links"]), 2)

    def test_reverse_lookup_lists_links_for_contributing_goal(self):
        link = GoalLink.objects.create(
            source_goal=self.financial_goal,
            contributing_goal=self.career_goal,
            link_type="income_growth",
        )
        self.client.force_authenticate(self.user)
        response = self.client.get(f"/goal/goals/{self.career_goal.id}/links/?direction=contributing")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["contributing_goal_id"], str(self.career_goal.id))
        self.assertEqual(response.data["links"][0]["id"], str(link.id))

    def test_delete_link_removes_only_link_record(self):
        link = GoalLink.objects.create(
            source_goal=self.financial_goal,
            contributing_goal=self.career_goal,
            link_type="income_growth",
        )
        self.client.force_authenticate(self.user)
        response = self.client.delete(f"/goal/goals/{self.financial_goal.id}/links/{link.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(GoalLink.objects.filter(id=link.id).exists())
        self.assertTrue(Goal.objects.filter(id=self.financial_goal.id).exists())
        self.assertTrue(Goal.objects.filter(id=self.career_goal.id).exists())

    def test_delete_contributing_goal_cascades_link_only(self):
        GoalLink.objects.create(
            source_goal=self.financial_goal,
            contributing_goal=self.career_goal,
            link_type="income_growth",
        )
        self.career_goal.delete()
        self.assertEqual(GoalLink.objects.filter(source_goal=self.financial_goal).count(), 0)
        self.assertTrue(Goal.objects.filter(id=self.financial_goal.id).exists())


class FinancialProgressAPIViewTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="financial-progress-owner@test.com",
            password="Password@123",
        )
        self.other_user = CustomUser.objects.create_user(
            email="financial-progress-other@test.com",
            password="Password@123",
        )
        self.goal = Goal.objects.create(
            user=self.user,
            title="Financial Progress Goal",
            primary_category="financial",
            target_date=timezone.localdate() + timedelta(days=365),
            financial_target_amount="500000.00",
            financial_current_saved="100000.00",
            financial_required_monthly_savings="20000.00",
        )
        self.url = f"/goal/goals/{self.goal.id}/financial-progress/"

    def test_post_upserts_month_and_recomputes_running_total(self):
        self.client.force_authenticate(self.user)
        first_response = self.client.post(
            self.url,
            data={
                "month": "2026-03-01",
                "planned_savings": "35000.00",
                "actual_savings": "28000.00",
                "notes": "First month",
            },
            format="json",
        )
        self.assertEqual(first_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(first_response.data["entries"]), 1)
        self.assertEqual(first_response.data["summary"]["running_total_saved"], 128000.0)

        second_response = self.client.post(
            self.url,
            data={
                "month": "2026-03-01",
                "planned_savings": "36000.00",
                "actual_savings": "30000.00",
                "notes": "Updated month",
            },
            format="json",
        )
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(second_response.data["entries"]), 1)
        self.assertEqual(second_response.data["summary"]["running_total_saved"], 130000.0)

    def test_get_returns_entries_and_projection_summary(self):
        FinancialProgressEntry.objects.create(
            goal=self.goal,
            user=self.user,
            month="2026-03-01",
            planned_savings="20000.00",
            actual_savings="20000.00",
            running_total_saved="120000.00",
        )
        FinancialProgressEntry.objects.create(
            goal=self.goal,
            user=self.user,
            month="2026-04-01",
            planned_savings="25000.00",
            actual_savings="25000.00",
            running_total_saved="145000.00",
        )
        self.client.force_authenticate(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["entries"]), 2)
        self.assertIn(response.data["summary"]["projection_status"], {"ahead", "on_track", "behind", "completed"})

    def test_projection_status_completed_when_target_reached(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            self.url,
            data={
                "month": "2026-03-01",
                "planned_savings": "450000.00",
                "actual_savings": "450000.00",
                "notes": "Goal complete",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["summary"]["projection_status"], "completed")
        self.assertEqual(response.data["summary"]["remaining_amount"], 0.0)

    def test_zero_actual_savings_returns_behind_with_no_projection_date(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            self.url,
            data={
                "month": "2026-03-01",
                "planned_savings": "20000.00",
                "actual_savings": "0.00",
                "notes": "No savings this month",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["summary"]["projection_status"], "behind")
        self.assertIsNone(response.data["summary"]["projected_completion_date"])

    def test_rejects_invalid_month_shape(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            self.url,
            data={
                "month": "2026-03-15",
                "planned_savings": "35000.00",
                "actual_savings": "28000.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "validation_error")
        self.assertIn("month", response.data["details"])

    def test_non_owner_access_is_denied(self):
        self.client.force_authenticate(self.other_user)
        get_response = self.client.get(self.url)
        self.assertEqual(get_response.status_code, status.HTTP_404_NOT_FOUND)
        post_response = self.client.post(
            self.url,
            data={
                "month": "2026-03-01",
                "planned_savings": "10000.00",
                "actual_savings": "10000.00",
            },
            format="json",
        )
        self.assertEqual(post_response.status_code, status.HTTP_404_NOT_FOUND)


class FinancialFeasibilityAPIViewTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="financial-feasibility-owner@test.com",
            password="Password@123",
        )
        self.url = "/goal/financial-feasibility/"
        self.payload = {
            "target_amount": "500000.00",
            "current_saved": "100000.00",
            "target_date": str(timezone.localdate() + timedelta(days=600)),
            "timeline_flexibility": "fixed",
        }

    def _create_profile(self, *, surplus_range="10k_30k", needs_review=False):
        return UserFinancialProfile.objects.create(
            user=self.user,
            employment_type="salaried_employee",
            monthly_income_range="50k_1l",
            monthly_surplus_range=surplus_range,
            primary_skill_area="technology",
            total_current_savings_range="under_5l",
            needs_review=needs_review,
            review_reason="",
        )

    def test_missing_profile_returns_contract_validation_error(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(self.url, data=self.payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "validation_error")
        self.assertIn("financial_profile", response.data["details"])

    def test_invalid_request_returns_contract_validation_error(self):
        self._create_profile()
        self.client.force_authenticate(self.user)
        response = self.client.post(
            self.url,
            data={
                "target_amount": "200000.00",
                "current_saved": "250000.00",
                "target_date": str(timezone.localdate() + timedelta(days=120)),
                "timeline_flexibility": "fixed",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "validation_error")
        self.assertIn("current_saved", response.data["details"])

    def test_invalid_timeline_choice_returns_contract_validation_error(self):
        self._create_profile()
        self.client.force_authenticate(self.user)
        response = self.client.post(
            self.url,
            data={**self.payload, "timeline_flexibility": "invalid"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "validation_error")
        self.assertIn("timeline_flexibility", response.data["details"])

    def test_feasibility_pass_response_shape(self):
        self._create_profile(surplus_range="10k_30k", needs_review=True)
        self.client.force_authenticate(self.user)
        response = self.client.post(self.url, data=self.payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["feasibility_status"], "pass")
        self.assertIn("adjustments", response.data)
        self.assertIn("suggested_target_date", response.data["adjustments"])
        self.assertIn("achievable_amount_by_original_date", response.data["adjustments"])
        self.assertEqual(response.data["needs_profile_review"], True)

    def test_feasibility_stretch_status(self):
        self._create_profile(surplus_range="10k_30k")
        self.client.force_authenticate(self.user)
        response = self.client.post(
            self.url,
            data={
                "target_amount": "640000.00",
                "current_saved": "100000.00",
                "target_date": str(timezone.localdate() + timedelta(days=300)),
                "timeline_flexibility": "fixed",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["feasibility_status"], "stretch")

    def test_feasibility_infeasible_status(self):
        self._create_profile(surplus_range="10k_30k")
        self.client.force_authenticate(self.user)
        response = self.client.post(
            self.url,
            data={
                "target_amount": "900000.00",
                "current_saved": "100000.00",
                "target_date": str(timezone.localdate() + timedelta(days=300)),
                "timeline_flexibility": "fixed",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["feasibility_status"], "infeasible")


class FinancialGoalLifecycleFeasibilityTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="financial-lifecycle-owner@test.com",
            password="Password@123",
        )
        self.client.force_authenticate(self.user)
        self._create_profile()

    def _create_profile(self):
        return UserFinancialProfile.objects.create(
            user=self.user,
            employment_type="salaried_employee",
            monthly_income_range="50k_1l",
            monthly_surplus_range="10k_30k",
            primary_skill_area="technology",
            total_current_savings_range="under_5l",
            needs_review=False,
            review_reason="",
        )

    def _financial_payload(self, **overrides):
        payload = {
            "title": "Financial Goal",
            "description": "Build corpus",
            "why_it_matters": ["Security"],
            "why_do_i_want_this": "I want long-term financial security.",
            "specific_measurable_target": "Accumulate the target corpus by the deadline.",
            "primary_category": "financial",
            "priority": "medium",
            "target_date": str(timezone.localdate() + timedelta(days=300)),
            **full_commitment_payload(),
            "financial_target_amount": "900000.00",
            "financial_current_saved": "100000.00",
            "financial_goal_type": "investment",
            "financial_timeline_flexibility": "fixed",
        }
        payload.update(overrides)
        return payload

    def test_create_infeasible_without_proceed_anyway_returns_contract_error(self):
        response = self.client.post("/goal/", data=self._financial_payload(), format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("financial_feasibility", response.data)
        self.assertEqual(response.data["financial_feasibility"]["status"], "infeasible")
        self.assertEqual(response.data["needs_profile_review"], False)
        self.assertFalse(Goal.objects.filter(user=self.user, title="Financial Goal").exists())

    def test_create_infeasible_with_proceed_anyway_persists_goal_and_commitment_record(self):
        response = self.client.post(
            "/goal/",
            data=self._financial_payload(financial_proceed_anyway=True),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        goal = Goal.objects.get(user=self.user, title="Financial Goal")
        self.assertEqual(goal.financial_feasibility_status, "infeasible")
        self.assertTrue(GoalCommitmentRecord.objects.filter(goal=goal, user=self.user).exists())

    def test_update_infeasible_without_proceed_anyway_is_rejected_and_unchanged(self):
        create_response = self.client.post(
            "/goal/",
            data=self._financial_payload(
                title="Feasible Goal",
                financial_target_amount="500000.00",
                target_date=str(timezone.localdate() + timedelta(days=600)),
            ),
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        goal = Goal.objects.get(id=create_response.data["goal"]["id"])
        previous_target_amount = goal.financial_target_amount
        previous_status = goal.financial_feasibility_status

        update_response = self.client.patch(
            f"/goal/goals/{goal.id}/",
            data={
                "financial_target_amount": "900000.00",
                "target_date": str(timezone.localdate() + timedelta(days=300)),
            },
            format="json",
        )
        self.assertEqual(update_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("financial_feasibility", update_response.data)

        goal.refresh_from_db()
        self.assertEqual(goal.financial_target_amount, previous_target_amount)
        self.assertEqual(goal.financial_feasibility_status, previous_status)

    def test_update_infeasible_with_proceed_anyway_persists_updated_metadata(self):
        create_response = self.client.post(
            "/goal/",
            data=self._financial_payload(
                title="Updatable Goal",
                financial_target_amount="500000.00",
                target_date=str(timezone.localdate() + timedelta(days=600)),
            ),
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        goal = Goal.objects.get(id=create_response.data["goal"]["id"])

        update_response = self.client.patch(
            f"/goal/goals/{goal.id}/",
            data={
                "financial_target_amount": "900000.00",
                "target_date": str(timezone.localdate() + timedelta(days=300)),
                "financial_proceed_anyway": True,
            },
            format="json",
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        goal.refresh_from_db()
        self.assertEqual(goal.financial_target_amount, 900000)
        self.assertEqual(goal.financial_feasibility_status, "infeasible")
        self.assertIsNotNone(goal.financial_required_monthly_savings)

    def test_pass_and_stretch_metadata_persist_on_create_and_update(self):
        create_response = self.client.post(
            "/goal/",
            data=self._financial_payload(
                title="Stretch Goal",
                financial_target_amount="640000.00",
            ),
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        goal = Goal.objects.get(id=create_response.data["goal"]["id"])
        self.assertEqual(goal.financial_feasibility_status, "stretch")

        update_response = self.client.patch(
            f"/goal/goals/{goal.id}/",
            data={
                "financial_target_amount": "500000.00",
                "target_date": str(timezone.localdate() + timedelta(days=600)),
            },
            format="json",
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        goal.refresh_from_db()
        self.assertEqual(goal.financial_feasibility_status, "pass")

    def test_create_with_hierarchy_infeasible_rejects_before_job_or_goal_creation(self):
        jobs_before = AIProcessingJob.objects.filter(user=self.user).count()
        response = self.client.post(
            "/goal/create-with-hierarchy/",
            data=self._financial_payload(title="Hierarchy Infeasible Goal"),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("financial_feasibility", response.data)
        self.assertFalse(Goal.objects.filter(user=self.user, title="Hierarchy Infeasible Goal").exists())
        jobs_after = AIProcessingJob.objects.filter(user=self.user).count()
        self.assertEqual(jobs_before, jobs_after)


class FinancialPlanSummaryBuilderTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="financial-plan-summary@test.com",
            password="Password@123",
        )
        self.goal = Goal.objects.create(
            user=self.user,
            title="Financial Growth Goal",
            primary_category="financial",
            target_date=timezone.localdate() + timedelta(days=365),
            financial_target_amount="1200000.00",
            financial_current_saved="100000.00",
            financial_feasibility_status="stretch",
            financial_required_monthly_savings="75000.00",
            financial_months_remaining=14,
            financial_gap_amount="1100000.00",
        )

    def _create_profile(self, employment_type: str):
        return UserFinancialProfile.objects.create(
            user=self.user,
            employment_type=employment_type,
            monthly_income_range="50k_1l",
            monthly_surplus_range="10k_30k",
            primary_skill_area="technology",
            total_current_savings_range="under_5l",
        )

    def test_uses_explicit_profile_branches(self):
        branches = [
            "student",
            "aspiring_founder",
            "early_career",
            "salaried_employee",
            "freelancer",
            "business_owner",
        ]
        observed = {}
        for branch in branches:
            UserFinancialProfile.objects.filter(user=self.user).delete()
            self._create_profile(branch)
            summary = build_financial_plan_summary(goal=self.goal, user=self.user)
            self.assertEqual(summary["employment_profile_used"], branch)
            self.assertGreater(len(summary["income_growth_path"]["actions"]), 0)
            observed[branch] = tuple(summary["income_growth_path"]["actions"])

        self.assertEqual(len(set(observed.values())), len(branches))

    def test_stretch_requires_income_growth_path(self):
        self._create_profile("salaried_employee")
        summary = build_financial_plan_summary(goal=self.goal, user=self.user)
        self.assertEqual(summary["feasibility_summary"]["feasibility_status"], "stretch")
        self.assertEqual(summary["income_growth_path"]["required"], True)
        self.assertGreater(summary["income_growth_path"]["target_monthly_uplift"], 0)

    def test_linked_goals_are_injected_into_summary(self):
        self._create_profile("salaried_employee")
        career_goal = Goal.objects.create(
            user=self.user,
            title="Promotion Goal",
            primary_category="career",
            target_date=timezone.localdate() + timedelta(days=180),
        )
        GoalLink.objects.create(
            source_goal=self.goal,
            contributing_goal=career_goal,
            link_type="income_growth",
        )

        summary = build_financial_plan_summary(goal=self.goal, user=self.user)
        self.assertEqual(len(summary["linked_goal_contributions"]), 1)
        link_payload = summary["linked_goal_contributions"][0]
        self.assertEqual(link_payload["contributing_goal_id"], str(career_goal.id))
        self.assertEqual(link_payload["contribution_type"], "income_growth")


class CreateWithHierarchyFinancialSummaryTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="financial-summary-endpoint@test.com",
            password="Password@123",
        )
        self.client.force_authenticate(self.user)
        UserFinancialProfile.objects.create(
            user=self.user,
            employment_type="salaried_employee",
            monthly_income_range="50k_1l",
            monthly_surplus_range="10k_30k",
            primary_skill_area="technology",
            total_current_savings_range="under_5l",
        )

    def test_sync_financial_create_includes_financial_plan_summary_when_ai_unavailable(self):
        with patch.dict("os.environ", {"OLLAMA_MODEL": "", "OLLAMA_HOST": ""}, clear=False):
            response = self.client.post(
                "/goal/create-with-hierarchy/?sync=true",
                data={
                    "title": "Financial Summary Goal",
                    "description": "Build corpus",
                    "why_it_matters": ["Security"],
                    "why_do_i_want_this": "I want a clear financial plan.",
                    "specific_measurable_target": "Reach the corpus target by the deadline.",
                    "primary_category": "financial",
                    "priority": "medium",
                    "target_date": str(timezone.localdate() + timedelta(days=300)),
                    **full_commitment_payload(),
                    "financial_target_amount": "640000.00",
                    "financial_current_saved": "100000.00",
                    "financial_goal_type": "investment",
                    "financial_timeline_flexibility": "fixed",
                    "financial_proceed_anyway": True,
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        goal = Goal.objects.get(user=self.user, title="Rich Goal")
        self.assertTrue(GoalCommitmentRecord.objects.filter(goal=goal, user=self.user).exists())


class FinancialFirstGoalLifecycleE2ETests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="financial-first-goal-e2e@test.com",
            password="Password@123",
        )
        self.client.force_authenticate(self.user)

    def test_first_financial_goal_profile_setup_to_feasibility_to_plan_generation(self):
        feasibility_payload = {
            "target_amount": "500000.00",
            "current_saved": "100000.00",
            "target_date": str(timezone.localdate() + timedelta(days=600)),
            "timeline_flexibility": "fixed",
        }

        missing_profile_feasibility = self.client.post(
            "/goal/financial-feasibility/",
            data=feasibility_payload,
            format="json",
        )
        self.assertEqual(missing_profile_feasibility.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(missing_profile_feasibility.data["error"], "validation_error")
        self.assertIn("financial_profile", missing_profile_feasibility.data["details"])

        create_profile = self.client.post(
            "/goal/financial-profile/",
            data={
                "employment_type": "salaried_employee",
                "monthly_income_range": "50k_1l",
                "monthly_surplus_range": "10k_30k",
                "primary_skill_area": "technology",
                "total_current_savings_range": "under_5l",
            },
            format="json",
        )
        self.assertEqual(create_profile.status_code, status.HTTP_201_CREATED)
        self.assertEqual(create_profile.data["needs_profile_review"], False)

        feasibility_response = self.client.post(
            "/goal/financial-feasibility/",
            data=feasibility_payload,
            format="json",
        )
        self.assertEqual(feasibility_response.status_code, status.HTTP_200_OK)
        self.assertEqual(feasibility_response.data["feasibility_status"], "pass")
        self.assertEqual(feasibility_response.data["needs_profile_review"], False)

        with patch.dict("os.environ", {"OLLAMA_MODEL": "", "OLLAMA_HOST": ""}, clear=False):
            create_goal = self.client.post(
                "/goal/create-with-hierarchy/?sync=true",
                data={
                    "title": "First Financial Goal E2E",
                    "description": "Cross-cutting lifecycle verification",
                    "why_it_matters": ["Stability"],
                    "why_do_i_want_this": "I want a stable emergency cushion.",
                    "specific_measurable_target": "Reach the target amount by the timeline.",
                    "primary_category": "financial",
                    "priority": "medium",
                    "target_date": feasibility_payload["target_date"],
                    **full_commitment_payload(),
                    "financial_target_amount": feasibility_payload["target_amount"],
                    "financial_current_saved": feasibility_payload["current_saved"],
                    "financial_goal_type": "investment",
                    "financial_timeline_flexibility": feasibility_payload["timeline_flexibility"],
                },
                format="json",
            )

        self.assertEqual(create_goal.status_code, status.HTTP_201_CREATED)
        goal = Goal.objects.get(user=self.user, title="First Financial Goal E2E")
        self.assertTrue(GoalCommitmentRecord.objects.filter(goal=goal, user=self.user).exists())


class FinancialGoalLinkLifecycleE2ETests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="financial-link-lifecycle-e2e@test.com",
            password="Password@123",
        )
        self.client.force_authenticate(self.user)

    def _create_profile(self):
        return self.client.post(
            "/goal/financial-profile/",
            data={
                "employment_type": "salaried_employee",
                "monthly_income_range": "50k_1l",
                "monthly_surplus_range": "10k_30k",
                "primary_skill_area": "technology",
                "total_current_savings_range": "under_5l",
            },
            format="json",
        )

    def _create_goal(self, *, title: str, primary_category: str, target_days: int = 180):
        payload = {
            "user": self.user,
            "title": title,
            "description": "E2E lifecycle verification",
            "why_it_matters": ["Consistency"],
            "primary_category": primary_category,
            "priority": "medium",
            "start_date": timezone.localdate(),
            "target_date": timezone.localdate() + timedelta(days=target_days),
        }
        if primary_category == "financial":
            payload.update(
                {
                    "financial_target_amount": 500000,
                    "financial_current_saved": 100000,
                    "financial_goal_type": "investment",
                    "financial_timeline_flexibility": "fixed",
                }
            )
        return str(Goal.objects.create(**payload).id)

    def test_link_lifecycle_triggers_review_signals_and_unlink_preserves_financial_goal(self):
        create_profile = self._create_profile()
        self.assertEqual(create_profile.status_code, status.HTTP_201_CREATED)
        self.assertEqual(create_profile.data["needs_profile_review"], False)

        financial_goal_id = self._create_goal(
            title="Financial Link E2E Goal",
            primary_category="financial",
            target_days=600,
        )

        career_goal_id = self._create_goal(
            title="Career Link Goal",
            primary_category="career",
            target_days=240,
        )
        personal_goal_id = self._create_goal(
            title="Personal Link Goal",
            primary_category="personal",
            target_days=240,
        )

        create_career_link = self.client.post(
            f"/goal/goals/{financial_goal_id}/links/",
            data={
                "contributing_goal": career_goal_id,
                "link_type": "income_growth",
            },
            format="json",
        )
        self.assertEqual(create_career_link.status_code, status.HTTP_201_CREATED)

        create_personal_link = self.client.post(
            f"/goal/goals/{financial_goal_id}/links/",
            data={
                "contributing_goal": personal_goal_id,
                "link_type": "skill_building",
            },
            format="json",
        )
        self.assertEqual(create_personal_link.status_code, status.HTTP_201_CREATED)

        list_links_before = self.client.get(f"/goal/goals/{financial_goal_id}/links/")
        self.assertEqual(list_links_before.status_code, status.HTTP_200_OK)
        self.assertEqual(len(list_links_before.data["links"]), 2)
        self.assertEqual(list_links_before.data["needs_profile_review"], False)

        complete_career = self.client.patch(
            f"/goal/goals/{career_goal_id}/",
            data={"status": "completed"},
            format="json",
        )
        self.assertEqual(complete_career.status_code, status.HTTP_200_OK)

        profile_after_completion = self.client.get("/goal/financial-profile/")
        self.assertEqual(profile_after_completion.status_code, status.HTTP_200_OK)
        self.assertEqual(profile_after_completion.data["needs_profile_review"], True)
        self.assertIn(
            "linked career goal",
            profile_after_completion.data["profile"]["review_reason"].lower(),
        )

        pause_personal = self.client.patch(
            f"/goal/goals/{personal_goal_id}/",
            data={"status": "paused"},
            format="json",
        )
        self.assertEqual(pause_personal.status_code, status.HTTP_200_OK)

        links_after_pause = self.client.get(f"/goal/goals/{financial_goal_id}/links/")
        self.assertEqual(links_after_pause.status_code, status.HTTP_200_OK)
        self.assertEqual(links_after_pause.data["needs_profile_review"], True)

        progress_surface = self.client.get(
            f"/goal/goals/{financial_goal_id}/financial-progress/",
        )
        self.assertEqual(progress_surface.status_code, status.HTTP_200_OK)
        self.assertEqual(progress_surface.data["needs_profile_review"], True)

        delete_career_link = self.client.delete(
            f"/goal/goals/{financial_goal_id}/links/{create_career_link.data['id']}/"
        )
        self.assertEqual(delete_career_link.status_code, status.HTTP_204_NO_CONTENT)

        remaining_links = self.client.get(f"/goal/goals/{financial_goal_id}/links/")
        self.assertEqual(remaining_links.status_code, status.HTTP_200_OK)
        self.assertEqual(len(remaining_links.data["links"]), 1)
        self.assertEqual(
            str(remaining_links.data["links"][0]["contributing_goal"]),
            personal_goal_id,
        )

        delete_personal_goal = self.client.delete(f"/goal/goals/{personal_goal_id}/")
        self.assertEqual(delete_personal_goal.status_code, status.HTTP_204_NO_CONTENT)

        links_after_contributing_delete = self.client.get(f"/goal/goals/{financial_goal_id}/links/")
        self.assertEqual(links_after_contributing_delete.status_code, status.HTTP_200_OK)
        self.assertEqual(len(links_after_contributing_delete.data["links"]), 0)
        self.assertTrue(Goal.objects.filter(id=financial_goal_id, user=self.user).exists())


class FinancialMonthlyReconciliationE2ETests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="financial-monthly-reconciliation-e2e@test.com",
            password="Password@123",
        )
        self.client.force_authenticate(self.user)

    def _create_profile(self):
        response = self.client.post(
            "/goal/financial-profile/",
            data={
                "employment_type": "salaried_employee",
                "monthly_income_range": "50k_1l",
                "monthly_surplus_range": "10k_30k",
                "primary_skill_area": "technology",
                "total_current_savings_range": "under_5l",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def _create_financial_goal(self) -> str:
        goal = Goal.objects.create(
            user=self.user,
            title="Financial Monthly Reconciliation Goal",
            description="Cross-cutting monthly reconciliation verification",
            why_it_matters=["Stability"],
            primary_category="financial",
            priority="medium",
            start_date=timezone.localdate(),
            target_date=timezone.localdate() + timedelta(days=180),
            financial_target_amount=250000,
            financial_current_saved=100000,
            financial_goal_type="investment",
            financial_timeline_flexibility="fixed",
        )
        return str(goal.id)

    def test_monthly_reconciliation_updates_projection_and_statuses(self):
        self._create_profile()
        financial_goal_id = self._create_financial_goal()
        progress_url = f"/goal/goals/{financial_goal_id}/financial-progress/"

        month_one = self.client.post(
            progress_url,
            data={
                "month": "2026-03-01",
                "planned_savings": "25000.00",
                "actual_savings": "0.00",
                "notes": "No contribution this month",
            },
            format="json",
        )
        self.assertEqual(month_one.status_code, status.HTTP_200_OK)
        self.assertEqual(len(month_one.data["entries"]), 1)
        self.assertEqual(month_one.data["summary"]["running_total_saved"], 100000.0)
        self.assertEqual(month_one.data["summary"]["projection_status"], "behind")
        self.assertIsNone(month_one.data["summary"]["projected_completion_date"])

        month_two = self.client.post(
            progress_url,
            data={
                "month": "2026-04-01",
                "planned_savings": "25000.00",
                "actual_savings": "60000.00",
                "notes": "Strong recovery month",
            },
            format="json",
        )
        self.assertEqual(month_two.status_code, status.HTTP_200_OK)
        self.assertEqual(len(month_two.data["entries"]), 2)
        self.assertEqual(month_two.data["summary"]["running_total_saved"], 160000.0)
        self.assertEqual(month_two.data["summary"]["projection_status"], "ahead")
        self.assertIsNotNone(month_two.data["summary"]["projected_completion_date"])

        month_three = self.client.post(
            progress_url,
            data={
                "month": "2026-05-01",
                "planned_savings": "25000.00",
                "actual_savings": "90000.00",
                "notes": "Reached target amount",
            },
            format="json",
        )
        self.assertEqual(month_three.status_code, status.HTTP_200_OK)
        self.assertEqual(len(month_three.data["entries"]), 3)
        self.assertEqual(month_three.data["summary"]["running_total_saved"], 250000.0)
        self.assertEqual(month_three.data["summary"]["remaining_amount"], 0.0)
        self.assertEqual(month_three.data["summary"]["projection_status"], "completed")

        get_after_reconciliation = self.client.get(progress_url)
        self.assertEqual(get_after_reconciliation.status_code, status.HTTP_200_OK)
        self.assertEqual(len(get_after_reconciliation.data["entries"]), 3)
        self.assertEqual(get_after_reconciliation.data["summary"]["running_total_saved"], 250000.0)
        self.assertEqual(get_after_reconciliation.data["summary"]["projection_status"], "completed")


class TaskTypeNormalizationTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="task-normalization@test.com",
            password="Password@123",
        )
        self.client.force_authenticate(self.user)

    @patch("goal.views.get_missing_ai_env_vars", return_value=[])
    @patch("goal.views.GoalHierarchyGenerator")
    @patch("goal.views.create_goal_for_user")
    def test_sync_create_with_hierarchy_normalizes_invented_task_types_before_db_write(
        self,
        mock_create_goal_for_user,
        mock_generator_cls,
        _mock_missing_ai_env,
    ):
        goal = Goal.objects.create(
            user=self.user,
            title="Normalization Goal",
            description="Check generated task type normalization",
            why_it_matters=["Integrity"],
            primary_category="career",
            priority="medium",
            target_date=timezone.localdate() + timedelta(days=45),
        )
        mock_create_goal_for_user.return_value = (goal, None)
        mock_generator_cls.return_value.generate_complete_hierarchy.return_value = {
            "status": "success",
            "data": {
                "milestones": [
                    {
                        "milestone_data": {"title": "Month 1", "description": "Desc"},
                        "subgoals": [
                            {
                                "subgoal_data": {"title": "Week 1", "description": "Desc"},
                                "tasks": [
                                    {"title": "Assess current state", "description": "Do work", "task_type": "assessment"},
                                    {"title": "Plan repo setup", "description": "Do work", "task_type": "planning"},
                                    {"title": "Do strange thing", "description": "Do work", "task_type": "wildcard_type"},
                                ],
                            }
                        ],
                    }
                ]
            },
        }

        response = self.client.post(
            "/goal/create-with-hierarchy/?sync=true",
            data={},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        task_types = list(Task.objects.order_by("display_order").values_list("task_type", flat=True))
        self.assertEqual(task_types, ["cognitive", "task", "task"])

    @patch("goal.views.get_missing_ai_env_vars", return_value=[])
    @patch("goal.views.GoalHierarchyGenerator")
    @patch("goal.views.create_goal_for_user")
    def test_sync_create_with_hierarchy_accepts_new_item_type_payload_before_migration_surface(
        self,
        mock_create_goal_for_user,
        mock_generator_cls,
        _mock_missing_ai_env,
    ):
        goal = Goal.objects.create(
            user=self.user,
            title="MVP Goal",
            description="Launch startup MVP",
            why_it_matters=["Revenue"],
            primary_category="personal",
            priority="medium",
            target_date=timezone.localdate() + timedelta(days=45),
        )
        mock_create_goal_for_user.return_value = (goal, None)
        mock_generator_cls.return_value.generate_complete_hierarchy.return_value = {
            "status": "success",
            "data": {
                "milestones": [
                    {
                        "milestone_data": {"title": "Month 1", "description": "Desc"},
                        "subgoals": [
                            {
                                "subgoal_data": {"title": "Week 1", "description": "Desc"},
                                "tasks": [
                                    {
                                        "title": "Create GitHub repo and push first commit",
                                        "description": "1. Create repo. 2. Push first commit.",
                                        "item_type": "task",
                                        "duration_minutes": 30,
                                        "frequency": "once",
                                        "sequence_position": 2,
                                        "is_prerequisite": True,
                                        "difficulty_level": 1,
                                        "session_type": None,
                                        "trigger_after_days": 0,
                                        "rationale": "You need codebase structure first.",
                                    }
                                ],
                            }
                        ],
                    }
                ]
            },
        }

        response = self.client.post(
            "/goal/create-with-hierarchy/?sync=true",
            data={},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        task = Task.objects.get(title="Create GitHub repo and push first commit")
        self.assertEqual(task.task_type, "task")
        self.assertEqual(task.item_type, "task")
        self.assertEqual(task.frequency, "once")
        self.assertEqual(task.difficulty_level, 1)
        self.assertIsNone(task.session_type)
        self.assertEqual(task.sequence_position, 2)
        self.assertTrue(task.is_prerequisite)
        self.assertEqual(task.trigger_after_days, 0)
        self.assertEqual(task.rationale, "You need codebase structure first.")

    @patch("goal.views.get_missing_ai_env_vars", return_value=[])
    @patch("goal.views.GoalHierarchyGenerator")
    @patch("goal.views.create_goal_for_user")
    def test_sync_create_with_hierarchy_keeps_missing_task_metadata_nullable(
        self,
        mock_create_goal_for_user,
        mock_generator_cls,
        _mock_missing_ai_env,
    ):
        goal = Goal.objects.create(
            user=self.user,
            title="Training Goal",
            description="Prepare for race day",
            why_it_matters=["Consistency"],
            primary_category="health",
            priority="medium",
            target_date=timezone.localdate() + timedelta(days=60),
        )
        mock_create_goal_for_user.return_value = (goal, None)
        mock_generator_cls.return_value.generate_complete_hierarchy.return_value = {
            "status": "success",
            "data": {
                "milestones": [
                    {
                        "milestone_data": {"title": "Month 1", "description": "Desc"},
                        "subgoals": [
                            {
                                "subgoal_data": {"title": "Week 1", "description": "Desc"},
                                "tasks": [
                                    {
                                        "title": "Walk for 20 minutes",
                                        "description": "1. Put on shoes. 2. Walk.",
                                        "task_type": "practice",
                                        "duration_minutes": 20,
                                    }
                                ],
                            }
                        ],
                    }
                ]
            },
        }

        response = self.client.post(
            "/goal/create-with-hierarchy/?sync=true",
            data={},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        task = Task.objects.get(title="Walk for 20 minutes")
        self.assertEqual(task.task_type, "physical")
        self.assertEqual(task.item_type, "physical")
        self.assertIsNone(task.frequency)
        self.assertIsNone(task.difficulty_level)
        self.assertIsNone(task.session_type)
        self.assertFalse(task.is_prerequisite)


class CategoryResolverTests(APITestCase):
    def test_health_resolves_to_fitness_for_marathon_goal(self):
        resolved = resolve_category("health", "Run a marathon", "Complete first marathon training plan")
        self.assertEqual(resolved, "fitness")

    def test_health_prepare_for_marathon_resolves_to_fitness(self):
        resolved = resolve_category("health", "Prepare for a Marathon", "Build endurance with a structured training plan")
        self.assertEqual(resolved, "fitness")

    def test_personal_mvp_goal_resolves_to_business(self):
        resolved = resolve_category("personal", "Launch SaaS MVP", "Ship beta to early users and monetize")
        self.assertEqual(resolved, "business")

    def test_personal_publish_mvp_goal_resolves_to_business(self):
        resolved = resolve_category("personal", "Publish MVP of DayOneGoal", "Launch beta, ship product updates, and generate revenue")
        self.assertEqual(resolved, "business")

    def test_personal_goal_without_signals_falls_back_to_productivity(self):
        resolved = resolve_category("personal", "Reset my life", "Need a better system")
        self.assertEqual(resolved, "productivity")

    def test_personal_anxiety_and_sleep_goal_resolves_to_wellness(self):
        resolved = resolve_category("personal", "Reduce anxiety and improve sleep", "Use meditation and therapy habits to sleep better")
        self.assertEqual(resolved, "wellness")

    def test_personal_relationship_goal_does_not_match_business_ship_signal(self):
        resolved = resolve_category("personal", "Improve my relationship with my family", "")
        self.assertEqual(resolved, "relationships")

    def test_personal_meditating_goal_uses_stem_match_and_does_not_match_creative_art_signal(self):
        resolved = resolve_category("personal", "Start meditating daily", "")
        self.assertEqual(resolved, "spiritual")
        self.assertNotEqual(resolved, "creative")

    def test_personal_screen_time_goal_resolves_to_digital_habits(self):
        resolved = resolve_category("personal", "Reduce screen time and stop scrolling Instagram", "")
        self.assertEqual(resolved, "digital_habits")

    def test_personal_prayer_goal_resolves_to_spiritual(self):
        resolved = resolve_category("personal", "Build a daily prayer habit", "Reconnect with faith and gratitude")
        self.assertEqual(resolved, "spiritual")

    def test_personal_family_communication_goal_resolves_to_relationships(self):
        resolved = resolve_category("personal", "Improve communication with my partner and family", "")
        self.assertEqual(resolved, "relationships")

    def test_personal_english_speaking_goal_resolves_to_communication(self):
        resolved = resolve_category(
            "personal",
            "Improve my English speaking and presentation skills",
            "Build fluency, vocabulary, and confidence in conversation",
        )
        self.assertEqual(resolved, "communication")

    def test_personal_university_thesis_goal_resolves_to_education(self):
        resolved = resolve_category("personal", "Complete my university thesis this semester", "")
        self.assertEqual(resolved, "education")

    def test_personal_novel_goal_resolves_to_creative(self):
        resolved = resolve_category("personal", "Write a novel", "Draft chapters every week")
        self.assertEqual(resolved, "creative")

    def test_career_goal_can_upgrade_to_business(self):
        resolved = resolve_category("career", "Launch startup MVP", "Acquire customers and grow revenue")
        self.assertEqual(resolved, "business")

    def test_career_machine_learning_engineer_goal_stays_career(self):
        resolved = resolve_category("career", "Become a Machine Learning Engineer", "Study deployment, interviews, and portfolio projects")
        self.assertEqual(resolved, "career")

    def test_financial_goal_resolves_to_finance(self):
        resolved = resolve_category("financial", "Save for emergency fund", "Build savings and budget monthly contributions")
        self.assertEqual(resolved, "finance")

    def test_health_diet_goal_can_upgrade_to_nutrition(self):
        resolved = resolve_category("health", "Fix my diet and meal prep", "Track protein and nutrition")
        self.assertEqual(resolved, "nutrition")


class CreateGoalWithHierarchyResolvedCategoryTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="resolved-category@test.com",
            password="Password@123",
        )
        self.client.force_authenticate(self.user)

    @patch("goal.views.get_missing_ai_env_vars", return_value=[])
    @patch("goal.views.GoalHierarchyGenerator")
    @patch("goal.views.create_goal_for_user")
    def test_sync_create_with_hierarchy_passes_resolved_category_to_generator(
        self,
        mock_create_goal_for_user,
        mock_generator_cls,
        _mock_missing_ai_env,
    ):
        goal = Goal.objects.create(
            user=self.user,
            title="Publish MVP of DayOneGoal",
            description="Launch startup beta, gain users, and generate revenue",
            why_it_matters=["Momentum"],
            primary_category="personal",
            priority="medium",
            target_date=timezone.localdate() + timedelta(days=45),
        )
        mock_create_goal_for_user.return_value = (goal, None)
        mock_generator_cls.return_value.generate_complete_hierarchy.return_value = {
            "status": "success",
            "data": {"milestones": []},
        }

        response = self.client.post(
            "/goal/create-with-hierarchy/?sync=true",
            data={},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        goal_data = mock_generator_cls.return_value.generate_complete_hierarchy.call_args.kwargs["goal_data"]
        self.assertEqual(goal_data["resolved_category"], "business")


class TaskMetadataContractTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="task-metadata@test.com",
            password="Password@123",
        )
        self.client.force_authenticate(self.user)
        goal = Goal.objects.create(
            user=self.user,
            title="Metadata Goal",
            primary_category="career",
            target_date=timezone.localdate() + timedelta(days=30),
        )
        milestone = Milestone.objects.create(
            goal=goal,
            title="Milestone",
            display_order=1,
        )
        subgoal = SubGoal.objects.create(
            milestone=milestone,
            title="Subgoal",
            display_order=0,
        )
        self.task = Task.objects.create(
            subgoal=subgoal,
            title="Write deployment checklist",
            description="1. Open docs. 2. Write checklist.",
            task_type="learning",
            item_type="cognitive",
            frequency="weekly",
            difficulty_level=3,
            session_type="review",
            trigger_after_days=2,
            is_prerequisite=True,
            sequence_position=4,
            rationale="You need a repeatable deployment path before launch.",
            priority="medium",
            estimated_duration_minutes=45,
            display_order=0,
        )

    def test_task_model_defaults_support_new_metadata_fields(self):
        task = Task.objects.create(
            subgoal=self.task.subgoal,
            title="Default metadata task",
            task_type="project",
            priority="medium",
            estimated_duration_minutes=15,
            display_order=1,
        )
        self.assertIsNone(task.item_type)
        self.assertIsNone(task.frequency)
        self.assertIsNone(task.difficulty_level)
        self.assertIsNone(task.session_type)
        self.assertFalse(task.is_prerequisite)
        self.assertEqual(task.sequence_position, 0)
        self.assertEqual(task.rationale, "")

    def test_task_detail_exposes_new_metadata_fields(self):
        response = self.client.get(f"/goal/tasks/{self.task.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["item_type"], "cognitive")
        self.assertEqual(response.data["frequency"], "weekly")
        self.assertEqual(response.data["difficulty_level"], 3)
        self.assertEqual(response.data["session_type"], "review")
        self.assertEqual(response.data["trigger_after_days"], 2)
        self.assertEqual(response.data["is_prerequisite"], True)
        self.assertEqual(response.data["sequence_position"], 4)
        self.assertEqual(response.data["rationale"], "You need a repeatable deployment path before launch.")

    def test_goal_hierarchy_payload_exposes_new_metadata_fields(self):
        goal_id = self.task.subgoal.milestone.goal.id
        response = self.client.get(f"/goal/goals/{goal_id}/hierarchy/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        task_payload = response.data["milestones"][0]["subgoals"][0]["tasks"][0]
        self.assertEqual(task_payload["item_type"], "cognitive")
        self.assertEqual(task_payload["frequency"], "weekly")
        self.assertEqual(task_payload["difficulty_level"], 3)
        self.assertEqual(task_payload["session_type"], "review")
        self.assertEqual(task_payload["trigger_after_days"], 2)
        self.assertEqual(task_payload["is_prerequisite"], True)
        self.assertEqual(task_payload["sequence_position"], 4)
        self.assertEqual(task_payload["rationale"], "You need a repeatable deployment path before launch.")

    def test_task_update_rejects_invalid_new_metadata_fields(self):
        response = self.client.put(
            f"/goal/tasks/{self.task.id}/",
            data={
                "item_type": "invalid",
                "frequency": "sometimes",
                "difficulty_level": 9,
                "session_type": "watch",
                "trigger_after_days": -1,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("item_type", response.data)
        self.assertIn("frequency", response.data)
        self.assertIn("difficulty_level", response.data)
        self.assertIn("session_type", response.data)
        self.assertIn("trigger_after_days", response.data)


class TaskTypeEnumValidationTests(APITestCase):
    def test_normalize_task_type_passes_through_valid_internal_types(self):
        for value in ("physical", "cognitive", "habit", "ritual", "task"):
            self.assertEqual(normalize_task_type(value, "fitness"), value)

    def test_normalize_task_type_maps_legacy_and_invented_values(self):
        expected_mappings = {
            "learning": "cognitive",
            "project": "task",
            "review": "cognitive",
            "assessment": "cognitive",
            "planning": "task",
            "evaluation": "cognitive",
            "exercise": "physical",
        }

        for raw_value, expected in expected_mappings.items():
            self.assertEqual(normalize_task_type(raw_value, "career"), expected)

    def test_normalize_task_type_maps_practice_by_category(self):
        self.assertEqual(normalize_task_type("practice", "fitness"), "physical")
        self.assertEqual(normalize_task_type("practice", "health"), "physical")
        self.assertEqual(normalize_task_type("practice", "nutrition"), "physical")
        self.assertEqual(normalize_task_type("practice", "career"), "cognitive")

    def test_normalize_task_type_defaults_unknown_values_to_task_with_warning(self):
        with self.assertLogs("ai.utils.validators", level="WARNING") as captured:
            normalized = normalize_task_type("brainstorm", "career")

        self.assertEqual(normalized, "task")
        self.assertIn("unknown type 'brainstorm'", captured.output[0])

    def test_save_task_persists_only_normalized_task_types(self):
        user = CustomUser.objects.create_user(
            email="task-type-save@test.com",
            password="Password@123",
        )
        goal = Goal.objects.create(
            user=user,
            title="Run a marathon",
            description="Complete first marathon training plan",
            primary_category="health",
            target_date=timezone.localdate() + timedelta(days=90),
        )
        milestone = Milestone.objects.create(
            goal=goal,
            title="Milestone",
            display_order=0,
        )
        subgoal = SubGoal.objects.create(
            milestone=milestone,
            title="Subgoal",
            display_order=0,
        )
        view = CreateGoalWithHierarchyAPIView()

        practice_task = view._save_task(
            subgoal,
            {
                "title": "Run intervals",
                "description": "1. Warm up. 2. Run. 3. Cool down.",
                "task_type": "practice",
                "item_type": "practice",
                "duration_minutes": 30,
            },
            1,
        )
        self.assertEqual(practice_task.task_type, "physical")
        self.assertEqual(practice_task.item_type, "physical")

        unknown_task = view._save_task(
            subgoal,
            {
                "title": "Unknown type task",
                "description": "1. Do the work.",
                "task_type": "brainstorm",
                "duration_minutes": 20,
            },
            2,
        )
        self.assertEqual(unknown_task.task_type, "task")
        self.assertEqual(unknown_task.item_type, "task")

    def test_save_task_leaves_new_metadata_nullable_when_missing(self):
        user = CustomUser.objects.create_user(
            email="task-nullable-save@test.com",
            password="Password@123",
        )
        goal = Goal.objects.create(
            user=user,
            title="Build a writing habit",
            description="Write consistently each week",
            primary_category="personal",
            target_date=timezone.localdate() + timedelta(days=30),
        )
        milestone = Milestone.objects.create(
            goal=goal,
            title="Milestone",
            display_order=0,
        )
        subgoal = SubGoal.objects.create(
            milestone=milestone,
            title="Subgoal",
            display_order=0,
        )
        view = CreateGoalWithHierarchyAPIView()

        task = view._save_task(
            subgoal,
            {
                "title": "Draft outline",
                "description": "1. Pick topic. 2. Write bullets.",
                "task_type": "planning",
                "duration_minutes": 25,
            },
            1,
        )

        self.assertEqual(task.task_type, "task")
        self.assertEqual(task.item_type, "task")
        self.assertIsNone(task.frequency)
        self.assertIsNone(task.difficulty_level)
        self.assertIsNone(task.session_type)
        self.assertFalse(task.is_prerequisite)


class TimelineInsightBoundaryContractTests(APITestCase):
    def test_rejects_mutation_fields_in_payload(self):
        with self.assertRaises(TimelineInsightBoundaryError):
            assert_read_only_timeline_insight_request(
                {
                    "goal_id": "goal-1",
                    "trigger_source": TIMELINE_INSIGHT_TRIGGER_USER_CLICK,
                    "status": "completed",
                }
            )

    def test_rejects_non_click_trigger_source(self):
        with self.assertRaises(TimelineInsightBoundaryError):
            assert_read_only_timeline_insight_request(
                {
                    "goal_id": "goal-1",
                    "trigger_source": "background_auto",
                }
            )

    def test_rejects_direct_gie_runtime_dependency_paths(self):
        with self.assertRaises(TimelineInsightBoundaryError):
            assert_no_gie_runtime_dependency(
                [
                    "goal.services.timeline_insight_service",
                    "gie.services.timeline_validation",
                ]
            )


class TimelineInsightProviderAdapterTests(APITestCase):
    @patch("goal.services.timeline_ai_provider.create_routed_provider")
    def test_default_provider_resolves_to_router_adapter(self, mock_provider_factory):
        adapter = get_timeline_ai_provider_adapter()
        self.assertIsInstance(adapter, OllamaTimelineAIProviderAdapter)
        mock_provider_factory.assert_called_once()

    def test_unknown_provider_raises_deterministic_error(self):
        with self.assertRaises(ValueError) as exc:
            get_timeline_ai_provider_adapter(provider_name="openai")
        self.assertIn("Unsupported LLM provider", str(exc.exception))

    def test_adapter_uses_base_provider_contract(self):
        class FakeProvider(BaseAIProvider):
            def __init__(self):
                super().__init__(model="fake-model", temperature=0.0)
                self.calls = []

            def generate_response(self, prompt: str, system_prompt=None, context=None):
                self.calls.append(
                    {
                        "prompt": prompt,
                        "system_prompt": system_prompt,
                        "context": context,
                    }
                )
                return AIResponse(content='{"status":"ok"}', model=self.model)

            def health_check(self):
                return True

        provider = FakeProvider()
        adapter = TimelineAIProviderAdapter(provider=provider)
        response = adapter.generate_timeline_insight(
            prompt="Assess goal feasibility",
            system_prompt="Return JSON only",
        )

        self.assertEqual(response.content, '{"status":"ok"}')
        self.assertEqual(response.model, "fake-model")
        self.assertEqual(provider.calls[0]["prompt"], "Assess goal feasibility")
        self.assertEqual(provider.calls[0]["system_prompt"], "Return JSON only")
        self.assertIsNone(provider.calls[0]["context"])


class _FakeTimelineAdapter:
    def __init__(self, responses=None, side_effect=None):
        self.responses = list(responses or [])
        self.side_effect = side_effect
        self.calls = []

    def generate_timeline_insight(self, *, prompt, system_prompt=None):
        self.calls.append({"prompt": prompt, "system_prompt": system_prompt})
        if self.side_effect is not None:
            raise self.side_effect
        if not self.responses:
            raise AssertionError("No fake responses configured.")
        next_response = self.responses.pop(0)
        if isinstance(next_response, Exception):
            raise next_response
        return AIResponse(content=next_response, model="fake-model")


class TimelineInsightDetectorTests(APITestCase):
    def setUp(self):
        self.current_goal = {
            "id": "goal-current",
            "title": "Build marathon endurance",
            "description": "Increase weekly mileage and improve race stamina.",
            "primary_category": "fitness",
            "priority": "high",
            "status": "in_progress",
            "target_date": "2026-08-01",
            "progress_percentage": 20,
        }

    def test_similar_goal_detector_returns_deduped_capped_findings(self):
        adapter = _FakeTimelineAdapter(
            responses=[
                '{"findings":["Strong overlap with active goal \'Run first marathon\'.","Strong overlap with active goal \'Run first marathon\'.","Related overlap with active goal \'Half-marathon speed block\'.","Overlap with another goal.","Fourth extra finding."]}'
            ]
        )

        findings = detect_similar_goals(
            current_goal=self.current_goal,
            active_goals=[{"title": "Run first marathon"}],
            provider_adapter=adapter,
        )

        self.assertEqual(len(findings), 3)
        self.assertEqual(findings[0], "Strong overlap with active goal 'Run first marathon'.")

    def test_similar_goal_detector_returns_empty_list_on_invalid_response(self):
        adapter = _FakeTimelineAdapter(responses=['{"findings":"not-a-list"}'])

        findings = detect_similar_goals(
            current_goal=self.current_goal,
            active_goals=[{"title": "Run first marathon"}],
            provider_adapter=adapter,
        )

        self.assertEqual(findings, [])

    def test_conflict_detector_returns_findings_for_intent_conflicts(self):
        adapter = _FakeTimelineAdapter(
            responses=[
                '{"findings":["Active goal \'Bulk up quickly\' competes with your current fat-loss target and recovery demands."]}'
            ]
        )

        findings = detect_goal_conflicts(
            current_goal=self.current_goal,
            active_goals=[{"title": "Bulk up quickly"}],
            provider_adapter=adapter,
        )

        self.assertEqual(
            findings,
            ["Active goal 'Bulk up quickly' competes with your current fat-loss target and recovery demands."],
        )

    def test_conflict_detector_returns_empty_list_on_provider_failure(self):
        adapter = _FakeTimelineAdapter(side_effect=RuntimeError("provider down"))

        findings = detect_goal_conflicts(
            current_goal=self.current_goal,
            active_goals=[{"title": "Bulk up quickly"}],
            provider_adapter=adapter,
        )

        self.assertEqual(findings, [])


class TimelineInsightServiceWaveOneTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="timeline-insight-service@test.com",
            password="Password@123",
        )
        self.goal = Goal.objects.create(
            user=self.user,
            title="Run marathon",
            description="Build endurance and complete race day confidently.",
            primary_category="fitness",
            priority="high",
            target_date=timezone.localdate() + timedelta(days=90),
            impact_dimensions={"specific_measurable_target": "Complete marathon under 4 hours"},
        )
        self.service = GoalTimelineInsightService()

    def test_finance_profile_is_only_loaded_for_finance_goals(self):
        profile = UserFinancialProfile.objects.create(
            user=self.user,
            employment_type="salaried_employee",
            monthly_income_range="50k_1l",
            monthly_surplus_range="10k_30k",
            primary_skill_area="technology",
            total_current_savings_range="5l_20l",
        )
        finance_goal = Goal.objects.create(
            user=self.user,
            title="Save for emergency fund",
            description="Build 6-month buffer",
            primary_category="finance",
            target_date=timezone.localdate() + timedelta(days=180),
            financial_target_amount=200000,
            financial_current_saved=50000,
        )
        self.assertIsNone(self.service._get_finance_profile(user=self.user, goal=self.goal))
        self.assertEqual(self.service._get_finance_profile(user=self.user, goal=finance_goal), profile)

    def test_missing_structure_detector_flags_all_wave1_cases(self):
        sparse_goal = Goal.objects.create(
            user=self.user,
            title="Get fit",
            description="",
            primary_category="finance",
            target_date=None,
            impact_dimensions={},
            financial_target_amount=None,
            financial_current_saved=None,
        )
        missing = self.service._detect_missing_structure(goal=sparse_goal)
        self.assertIn("No measurable target is defined yet.", missing)
        self.assertIn("No clear timeframe is set for completion.", missing)
        self.assertIn("No clear baseline is available to measure progress from.", missing)
        self.assertIn("Goal details are too broad; add specific scope and constraints.", missing)

    def test_missing_structure_detector_avoids_false_positives_for_specific_goal(self):
        complete_goal = Goal.objects.create(
            user=self.user,
            title="Complete AWS Architect certification",
            description="Study 6 hours weekly, complete 12 mock tests, and pass exam by target date.",
            primary_category="career",
            target_date=timezone.localdate() + timedelta(days=160),
            impact_dimensions={"specific_measurable_target": "Pass AWS SA Pro exam"},
        )
        missing = self.service._detect_missing_structure(goal=complete_goal)
        self.assertNotIn("No measurable target is defined yet.", missing)
        self.assertNotIn("No clear timeframe is set for completion.", missing)
        self.assertNotIn("Goal details are too broad; add specific scope and constraints.", missing)

    def test_feasibility_status_mapping_uses_three_tiers(self):
        self.assertEqual(self.service._map_status(90.0), "realistic")
        self.assertEqual(self.service._map_status(70.0), "stretch")
        self.assertEqual(self.service._map_status(45.0), "unrealistic")

    def test_analyze_is_read_only_and_returns_contract_shape(self):
        Goal.objects.create(
            user=self.user,
            title="Run marathon safely",
            description="Build endurance and avoid injury.",
            primary_category="fitness",
            target_date=timezone.localdate() + timedelta(days=95),
            status="in_progress",
        )
        before_counts = {
            "goals": Goal.objects.count(),
            "milestones": Milestone.objects.count(),
            "subgoals": SubGoal.objects.count(),
            "tasks": Task.objects.count(),
        }
        payload = self.service.analyze(user=self.user, goal=self.goal)
        after_counts = {
            "goals": Goal.objects.count(),
            "milestones": Milestone.objects.count(),
            "subgoals": SubGoal.objects.count(),
            "tasks": Task.objects.count(),
        }
        self.assertEqual(before_counts, after_counts)
        self.assertIn("feasibility", payload)
        self.assertIn("missing_elements", payload)
        self.assertIn("conflicts", payload)
        self.assertIn(payload["feasibility"]["status"], {"realistic", "stretch", "unrealistic"})
        self.assertIsInstance(payload["missing_elements"], list)
        self.assertIsInstance(payload["conflicts"], list)

    def test_health_profile_lookup_uses_active_profile(self):
        from routine.models import HealthProfile

        first_profile = HealthProfile.objects.create(user=self.user, stress_level="high")
        active_profile = HealthProfile.objects.create(user=self.user, stress_level="low")
        first_profile.refresh_from_db()
        active_profile.refresh_from_db()

        resolved = self.service._get_latest_health_profile(user=self.user)
        self.assertFalse(first_profile.is_active)
        self.assertTrue(active_profile.is_active)
        self.assertEqual(resolved.id, active_profile.id)


class TimelineInsightServiceWaveTwoTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="timeline-insight-wave2@test.com",
            password="Password@123",
        )
        self.goal = Goal.objects.create(
            user=self.user,
            title="Lose 10 kg safely",
            description="Reduce body fat while preserving strength with measured training and nutrition.",
            primary_category="fitness",
            priority="high",
            status="in_progress",
            target_date=timezone.localdate() + timedelta(days=120),
            impact_dimensions={"specific_measurable_target": "Lose 10 kg in 4 months"},
        )
        self.service = GoalTimelineInsightService()

    def test_validate_goal_insight_payload_accepts_valid_shape(self):
        payload = self.service._validate_goal_insight_payload(
            {
                "feasibility": {
                    "status": "stretch",
                    "summary": "Timeline is possible with consistent weekly execution.",
                    "achievable_version": None,
                },
                "missing_elements": ["Baseline body-fat percentage is missing."],
                "conflicts": ["Current bulking goal may compete with this cut."],
            }
        )

        self.assertEqual(payload["feasibility"]["status"], "stretch")
        self.assertEqual(payload["missing_elements"], ["Baseline body-fat percentage is missing."])

    def test_validate_goal_insight_payload_rejects_invalid_shape(self):
        with self.assertRaises(ValueError):
            self.service._validate_goal_insight_payload(
                {
                    "feasibility": {
                        "status": "maybe",
                        "summary": "Bad",
                        "achievable_version": None,
                    },
                    "missing_elements": [],
                    "conflicts": [],
                }
            )

    @patch("goal.services.timeline_insight_service.get_timeline_ai_provider_adapter")
    @patch("goal.services.timeline_insight_service.detect_goal_conflicts")
    @patch("goal.services.timeline_insight_service.detect_similar_goals")
    def test_analyze_retries_once_after_parse_failure(
        self,
        mock_similar,
        mock_conflicts,
        mock_provider_factory,
    ):
        mock_similar.return_value = ["Overlap with active goal 'Build race endurance'."]
        mock_conflicts.return_value = ["Bulking goal may compete with this cut."]
        adapter = _FakeTimelineAdapter(
            responses=[
                "not-json",
                '{"feasibility":{"status":"stretch","summary":"Timeline is achievable with steady weekly execution.","achievable_version":"Aim for 6 to 8 kg first."},"missing_elements":["Baseline calorie intake is not defined yet."],"conflicts":["Bulking goal may compete with this cut."]}',
            ]
        )
        mock_provider_factory.return_value = adapter

        payload = self.service.analyze(user=self.user, goal=self.goal)

        self.assertEqual(len(adapter.calls), 2)
        self.assertEqual(payload["feasibility"]["status"], "stretch")
        self.assertEqual(payload["conflicts"], ["Bulking goal may compete with this cut."])
        self.assertIn("STRICT REPAIR MODE", adapter.calls[1]["prompt"])

    @patch("goal.services.timeline_insight_service.get_timeline_ai_provider_adapter")
    @patch("goal.services.timeline_insight_service.detect_goal_conflicts")
    @patch("goal.services.timeline_insight_service.detect_similar_goals")
    def test_analyze_returns_deterministic_fallback_after_two_failures(
        self,
        mock_similar,
        mock_conflicts,
        mock_provider_factory,
    ):
        mock_similar.return_value = ["Strong overlap with active goal 'Run a 10k race'."]
        mock_conflicts.return_value = ["Muscle-gain goal may compete with aggressive fat-loss pacing."]
        adapter = _FakeTimelineAdapter(responses=["not-json", '{"feasibility":{"status":"bad"}}'])
        mock_provider_factory.return_value = adapter

        payload = self.service.analyze(user=self.user, goal=self.goal)

        self.assertEqual(len(adapter.calls), 2)
        self.assertIn(payload["feasibility"]["status"], {"realistic", "stretch", "unrealistic"})
        self.assertEqual(
            payload["conflicts"],
            [
                "Strong overlap with active goal 'Run a 10k race'.",
                "Muscle-gain goal may compete with aggressive fat-loss pacing.",
            ],
        )

    @patch("goal.services.timeline_insight_service.get_timeline_ai_provider_adapter")
    @patch("goal.services.timeline_insight_service.detect_goal_conflicts")
    @patch("goal.services.timeline_insight_service.detect_similar_goals")
    def test_analyze_uses_safe_fallback_when_provider_raises(
        self,
        mock_similar,
        mock_conflicts,
        mock_provider_factory,
    ):
        mock_similar.return_value = []
        mock_conflicts.return_value = []
        mock_provider_factory.return_value = _FakeTimelineAdapter(side_effect=RuntimeError("Ollama generation failed"))

        payload = self.service.analyze(user=self.user, goal=self.goal)

        self.assertIn(payload["feasibility"]["status"], {"realistic", "stretch", "unrealistic"})
        self.assertEqual(payload["conflicts"], [])

    @patch("goal.services.timeline_insight_service.get_timeline_ai_provider_adapter", side_effect=RuntimeError("bad config"))
    def test_analyze_uses_fallback_when_provider_factory_raises(self, _mock_provider_factory):
        payload = self.service.analyze(user=self.user, goal=self.goal)

        self.assertIn(payload["feasibility"]["status"], {"realistic", "stretch", "unrealistic"})
        self.assertEqual(payload["conflicts"], [])


class TimelineInsightEndpointTests(APITestCase):
    def setUp(self):
        self.owner = CustomUser.objects.create_user(
            email="timeline-insight-owner@test.com",
            password="Password@123",
        )
        self.other_user = CustomUser.objects.create_user(
            email="timeline-insight-other@test.com",
            password="Password@123",
        )
        self.goal = Goal.objects.create(
            user=self.owner,
            title="Save emergency fund",
            description="Save consistently every month for safety net.",
            primary_category="finance",
            target_date=timezone.localdate() + timedelta(days=240),
            financial_target_amount=300000,
            financial_current_saved=100000,
            impact_dimensions={"specific_measurable_target": "Accumulate 300000 emergency reserve"},
        )
        self.url = f"/goal/goals/{self.goal.id}/timeline-insight/"

    def test_owner_post_returns_payload_shape(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            self.url,
            data={"trigger_source": "user_click"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("feasibility", response.data)
        self.assertIn("missing_elements", response.data)
        self.assertIn("conflicts", response.data)
        self.assertIn(response.data["feasibility"]["status"], {"realistic", "stretch", "unrealistic"})
        self.assertIsInstance(response.data["missing_elements"], list)
        self.assertIsInstance(response.data["conflicts"], list)

    def test_endpoint_rejects_non_click_trigger(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            self.url,
            data={"trigger_source": "background_auto"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "validation_error")

    def test_endpoint_rejects_mutation_fields(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            self.url,
            data={
                "trigger_source": "user_click",
                "title": "Mutate attempt",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "validation_error")

    def test_endpoint_returns_404_for_non_owner(self):
        self.client.force_authenticate(self.other_user)
        response = self.client.post(
            self.url,
            data={"trigger_source": "user_click"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_endpoint_is_read_only_without_side_effects(self):
        self.client.force_authenticate(self.owner)
        before_counts = {
            "goals": Goal.objects.count(),
            "milestones": Milestone.objects.count(),
            "subgoals": SubGoal.objects.count(),
            "tasks": Task.objects.count(),
        }
        response = self.client.post(
            self.url,
            data={"trigger_source": "user_click"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        after_counts = {
            "goals": Goal.objects.count(),
            "milestones": Milestone.objects.count(),
            "subgoals": SubGoal.objects.count(),
            "tasks": Task.objects.count(),
        }
        self.assertEqual(before_counts, after_counts)

    @patch("goal.services.timeline_insight_service.get_timeline_ai_provider_adapter")
    @patch("goal.services.timeline_insight_service.detect_goal_conflicts")
    @patch("goal.services.timeline_insight_service.detect_similar_goals")
    def test_endpoint_returns_safe_fallback_payload_when_ai_fails(
        self,
        mock_similar,
        mock_conflicts,
        mock_provider_factory,
    ):
        mock_similar.return_value = []
        mock_conflicts.return_value = []
        mock_provider_factory.return_value = _FakeTimelineAdapter(
            side_effect=RuntimeError("Ollama generation failed: connection refused")
        )
        self.client.force_authenticate(self.owner)

        response = self.client.post(
            self.url,
            data={"trigger_source": "user_click"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("feasibility", response.data)
        self.assertNotIn("Ollama generation failed", str(response.data))

    @patch("goal.views.GoalTimelineInsightService._analyze")
    def test_endpoint_reuses_cached_payload_when_inputs_are_unchanged(self, mock_analyze):
        mock_analyze.return_value = {
            "feasibility": {
                "status": "stretch",
                "summary": "Cached timeline insight.",
                "achievable_version": "Phase the savings goal into two checkpoints.",
            },
            "missing_elements": [],
            "conflicts": [],
        }
        self.client.force_authenticate(self.owner)

        first_response = self.client.post(
            self.url,
            data={"trigger_source": "user_click"},
            format="json",
        )
        second_response = self.client.post(
            self.url,
            data={"trigger_source": "user_click"},
            format="json",
        )

        self.assertEqual(first_response.status_code, status.HTTP_200_OK)
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        self.assertEqual(first_response.data, second_response.data)
        self.assertEqual(mock_analyze.call_count, 1)

        self.goal.refresh_from_db()
        self.assertEqual(self.goal.timeline_insight_payload, first_response.data)
        self.assertTrue(self.goal.timeline_insight_fingerprint)
        self.assertIsNotNone(self.goal.timeline_insight_generated_at)

    @patch("goal.views.GoalTimelineInsightService._analyze")
    def test_endpoint_regenerates_cached_payload_after_goal_input_changes(self, mock_analyze):
        mock_analyze.side_effect = [
            {
                "feasibility": {
                    "status": "stretch",
                    "summary": "Original insight.",
                    "achievable_version": None,
                },
                "missing_elements": [],
                "conflicts": [],
            },
            {
                "feasibility": {
                    "status": "realistic",
                    "summary": "Updated insight after target date change.",
                    "achievable_version": None,
                },
                "missing_elements": [],
                "conflicts": [],
            },
        ]
        self.client.force_authenticate(self.owner)

        first_response = self.client.post(
            self.url,
            data={"trigger_source": "user_click"},
            format="json",
        )
        self.goal.target_date = self.goal.target_date + timedelta(days=60)
        self.goal.save(update_fields=["target_date", "updated_at"])

        second_response = self.client.post(
            self.url,
            data={"trigger_source": "user_click"},
            format="json",
        )

        self.assertEqual(first_response.status_code, status.HTTP_200_OK)
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        self.assertEqual(mock_analyze.call_count, 2)
        self.assertNotEqual(first_response.data["feasibility"]["summary"], second_response.data["feasibility"]["summary"])

        self.goal.refresh_from_db()
        self.assertEqual(self.goal.timeline_insight_payload, second_response.data)


class TimelineOverviewInsightServiceTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="timeline-overview-service@test.com",
            password="Password@123",
        )
        self.first_goal = Goal.objects.create(
            user=self.user,
            title="Launch product beta",
            description="Ship beta with a small pilot cohort.",
            primary_category="business",
            priority="high",
            status="in_progress",
            progress_percentage=45,
            target_date=timezone.localdate() + timedelta(days=20),
        )
        self.second_goal = Goal.objects.create(
            user=self.user,
            title="Improve fitness baseline",
            description="Train four times per week and improve endurance.",
            primary_category="fitness",
            priority="medium",
            status="in_progress",
            progress_percentage=35,
            target_date=timezone.localdate() + timedelta(days=40),
        )
        self.task_list = DailyTaskList.objects.create(
            user=self.user,
            date=timezone.localdate(),
            total_tasks=4,
            completed_tasks=2,
            completion_percentage=50,
            status="in_progress",
        )
        DailyTaskItem.objects.create(
            task_list=self.task_list,
            item_type="goal_task",
            related_goal=self.first_goal,
            title="Pilot onboarding calls",
            priority="high",
            estimated_minutes=180,
            time_slot="morning",
        )
        DailyTaskItem.objects.create(
            task_list=self.task_list,
            item_type="goal_task",
            related_goal=self.second_goal,
            title="Workout session",
            priority="high",
            estimated_minutes=90,
            time_slot="morning",
        )
        self.service = TimelineOverviewInsightService()

    @patch("goal.services.timeline_overview_insight_service.get_timeline_ai_provider_adapter", side_effect=RuntimeError("offline"))
    def test_service_returns_mobile_shape_with_real_progress_inputs(self, _mock_provider_factory):
        payload = self.service.analyze(user=self.user)

        self.assertEqual(set(payload.keys()), {
            "plan_health_score",
            "conflicts",
            "at_risk_goals",
            "recommendations",
            "daily_hours_planned",
            "delay_per_missed_day",
            "weekly_success_rate",
            "competing_goals_count",
            "general_note",
        })
        self.assertIsInstance(payload["conflicts"], list)
        self.assertIsInstance(payload["at_risk_goals"], list)
        self.assertIsInstance(payload["recommendations"], list)
        self.assertEqual(payload["competing_goals_count"], 2)
        self.assertEqual(payload["weekly_success_rate"], 0.5)
        self.assertGreaterEqual(payload["daily_hours_planned"], 4.0)
        self.assertTrue(any(item["goal_id"] == str(self.first_goal.id) for item in payload["at_risk_goals"]))


class TimelineOverviewInsightEndpointTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="timeline-overview-endpoint@test.com",
            password="Password@123",
        )
        self.goal = Goal.objects.create(
            user=self.user,
            title="Grow consulting pipeline",
            description="Close two retainer clients.",
            primary_category="career",
            status="in_progress",
            progress_percentage=55,
            target_date=timezone.localdate() + timedelta(days=25),
        )
        self.url = "/goal/goals/timeline-insight/"

    def test_endpoint_requires_authentication(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch("goal.services.timeline_overview_insight_service.get_timeline_ai_provider_adapter")
    def test_endpoint_returns_ai_validated_mobile_shape(self, mock_provider_factory):
        mock_provider_factory.return_value = _FakeTimelineAdapter(
            responses=[
                '{"plan_health_score":81.2,"conflicts":[],"at_risk_goals":[{"goal_id":"%s","goal_title":"Grow consulting pipeline","progress_percentage":55,"days_remaining":25,"description":"Grow consulting pipeline is at risk - 55%% done with 25 day(s) left."}],"recommendations":[{"text":"Protect two high-value sales blocks this week."}],"daily_hours_planned":3.5,"delay_per_missed_day":2,"weekly_success_rate":0.74,"competing_goals_count":1,"general_note":"Your plan looks realistic. Keep this pace."}'
                % self.goal.id
            ]
        )
        self.client.force_authenticate(self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["plan_health_score"], 81.2)
        self.assertEqual(response.data["at_risk_goals"][0]["goal_id"], str(self.goal.id))
        self.assertEqual(response.data["recommendations"][0]["text"], "Protect two high-value sales blocks this week.")


class GoalCategoryNormalizationContractTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="goal-category-normalization@test.com",
            password="Password@123",
        )
        UserFinancialProfile.objects.create(
            user=self.user,
            employment_type="salaried_employee",
            monthly_income_range="50k_1l",
            monthly_surplus_range="10k_30k",
            primary_skill_area="technology",
            total_current_savings_range="5l_20l",
        )
        self.client.force_authenticate(self.user)

    def test_create_accepts_legacy_financial_and_persists_finance(self):
        payload = full_commitment_payload(user=self.user)
        payload.update(
            {
                "title": "Emergency fund",
                "description": "Save money for emergencies.",
                "why_it_matters": ["Security"],
                "why_do_i_want_this": "I want a safer financial buffer for emergencies.",
                "specific_measurable_target": "Save 200000 for a dedicated emergency fund.",
                "primary_category": "financial",
                "priority": "medium",
                "target_date": str(timezone.localdate() + timedelta(days=180)),
                "financial_target_amount": "200000.00",
                "financial_current_saved": "50000.00",
                "financial_goal_type": "emergency_fund",
                "financial_timeline_flexibility": "fixed",
                "financial_proceed_anyway": True,
            }
        )
        response = self.client.post(
            "/goal/",
            data=payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        goal = Goal.objects.get(user=self.user, title="Emergency fund")
        self.assertEqual(goal.primary_category, "finance")

    @patch("goal.services.goal_domain.classify_goal_category")
    def test_create_trusts_explicit_primary_category_without_reclassification(self, mock_classify_goal_category):
        payload = full_commitment_payload(
            user=self.user,
            goal_data={
                "title": "Sleep better",
                "description": "Reduce anxiety and improve sleep quality.",
                "why_it_matters": ["Calm", "Recovery"],
                "why_do_i_want_this": "I want steadier energy and less anxiety.",
                "specific_measurable_target": "Sleep 7.5 hours on most nights.",
                "primary_category": "wellness",
                "target_date": str(timezone.localdate() + timedelta(days=45)),
            },
        )
        payload.update(
            {
                "title": "Sleep better",
                "description": "Reduce anxiety and improve sleep quality.",
                "why_it_matters": ["Calm", "Recovery"],
                "why_do_i_want_this": "I want steadier energy and less anxiety.",
                "specific_measurable_target": "Sleep 7.5 hours on most nights.",
                "primary_category": "wellness",
                "priority": "medium",
                "target_date": str(timezone.localdate() + timedelta(days=90)),
            }
        )
        request = APIRequestFactory().post("/goal/", payload, format="json")
        request.user = self.user

        goal, errors = create_goal_for_user(
            request_data=payload,
            user=self.user,
            request=request,
        )

        self.assertIsNone(errors)
        self.assertIsNotNone(goal)
        self.assertEqual(goal.primary_category, "wellness")
        mock_classify_goal_category.assert_not_called()

    @patch("goal.services.goal_domain.classify_goal_category")
    def test_create_trusts_gie_goal_domain_without_reclassification(self, mock_classify_goal_category):
        payload = full_commitment_payload(
            user=self.user,
            goal_data={
                "title": "Sleep better",
                "description": "Reduce anxiety and improve sleep quality.",
                "why_it_matters": ["Calm", "Recovery"],
                "why_do_i_want_this": "I want steadier energy and less anxiety.",
                "specific_measurable_target": "Sleep 7.5 hours on most nights.",
                "primary_category": "wellness",
                "target_date": str(timezone.localdate() + timedelta(days=90)),
            },
        )
        payload.update(
            {
                "title": "Sleep better",
                "description": "Reduce anxiety and improve sleep quality.",
                "why_it_matters": ["Calm", "Recovery"],
                "why_do_i_want_this": "I want steadier energy and less anxiety.",
                "specific_measurable_target": "Sleep 7.5 hours on most nights.",
                "priority": "medium",
                "target_date": str(timezone.localdate() + timedelta(days=45)),
            }
        )
        payload.pop("primary_category", None)
        payload["goal_domain"] = "wellness"

        request = APIRequestFactory().post("/goal/create-with-hierarchy/", payload, format="json")
        request.user = self.user

        goal, errors = create_goal_for_user(
            request_data=payload,
            user=self.user,
            request=request,
        )

        self.assertIsNone(errors)
        self.assertIsNotNone(goal)
        self.assertEqual(goal.primary_category, "wellness")
        mock_classify_goal_category.assert_not_called()

    def test_patch_accepts_legacy_health_and_persists_fitness(self):
        goal = Goal.objects.create(
            user=self.user,
            title="Get stronger",
            description="Lift weights consistently.",
            primary_category="career",
            target_date=timezone.localdate() + timedelta(days=90),
        )

        response = self.client.patch(
            f"/goal/goals/{goal.id}/",
            data={"primary_category": "health"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        goal.refresh_from_db()
        self.assertEqual(goal.primary_category, "fitness")

    def test_patch_accepts_legacy_personal_and_persists_productivity(self):
        goal = Goal.objects.create(
            user=self.user,
            title="Get organized",
            description="Build a better weekly planning system.",
            primary_category="career",
            target_date=timezone.localdate() + timedelta(days=60),
        )

        response = self.client.patch(
            f"/goal/goals/{goal.id}/",
            data={"primary_category": "personal"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        goal.refresh_from_db()
        self.assertEqual(goal.primary_category, "productivity")

    def test_list_filter_accepts_legacy_financial_query_and_matches_canonical_rows(self):
        Goal.objects.create(
            user=self.user,
            title="Finance Goal",
            primary_category="finance",
            target_date=timezone.localdate() + timedelta(days=120),
        )
        Goal.objects.create(
            user=self.user,
            title="Career Goal",
            primary_category="career",
            target_date=timezone.localdate() + timedelta(days=120),
        )

        response = self.client.get("/goal/goals/?category=financial")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["goals"][0]["primary_category"], "finance")


class GoalCategoryPillarContractTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="goal-category-pillars@test.com",
            password="Password@123",
        )
        self.client.force_authenticate(self.user)

    def _full_payload(self, **overrides):
        payload = full_commitment_payload(user=self.user)
        payload.update(
            {
                "title": "Pillar Contract Goal",
                "description": "Ship the next version with clear milestones.",
                "why_it_matters": ["Momentum"],
                "why_do_i_want_this": "I want consistent execution.",
                "specific_measurable_target": "Release one stable version in 90 days.",
                "primary_category": "career",
                "priority": "medium",
                "target_date": str(timezone.localdate() + timedelta(days=90)),
            }
        )
        payload.update(overrides)
        return payload

    def test_canonical_to_pillar_mapping_is_complete_for_all_goal_categories(self):
        for category in GOAL_CATEGORIES:
            pillar = canonical_to_pillar(category)
            self.assertIn(
                pillar,
                {"Money", "Health", "Career", "Learning", "Relationships", "Personal"},
            )

    def test_pillar_to_default_canonical_mapping_matches_contract(self):
        self.assertEqual(pillar_to_default_canonical("Money"), "finance")
        self.assertEqual(pillar_to_default_canonical("Health"), "fitness")
        self.assertEqual(pillar_to_default_canonical("Career"), "career")
        self.assertEqual(pillar_to_default_canonical("Learning"), "learning")
        self.assertEqual(pillar_to_default_canonical("Relationships"), "relationships")
        self.assertEqual(pillar_to_default_canonical("Personal"), "productivity")

    def test_create_with_only_category_pillar_maps_to_default_canonical(self):
        payload = self._full_payload()
        payload.pop("primary_category")
        payload["category_pillar"] = "Career"

        response = self.client.post("/goal/", data=payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        goal = Goal.objects.get(user=self.user, title="Pillar Contract Goal")
        self.assertEqual(goal.primary_category, "career")
        self.assertEqual(response.data["category_pillar"], "Career")

    def test_create_prefers_primary_category_when_both_primary_and_pillar_provided(self):
        payload = self._full_payload(
            primary_category="learning",
            category_pillar="Money",
        )
        payload["contract_snapshot"] = full_commitment_payload(
            user=self.user,
            goal_data={
                "title": payload["title"],
                "description": payload["description"],
                "why_it_matters": payload["why_it_matters"],
                "why_do_i_want_this": payload["why_do_i_want_this"],
                "specific_measurable_target": payload["specific_measurable_target"],
                "primary_category": "learning",
                "target_date": payload["target_date"],
            },
            signed_name=payload["signed_name"],
            signed_at=payload["signed_at"],
        )["contract_snapshot"]

        response = self.client.post("/goal/", data=payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        goal = Goal.objects.get(user=self.user, title="Pillar Contract Goal")
        self.assertEqual(goal.primary_category, "learning")
        self.assertEqual(response.data["category_pillar"], "Learning")

    def test_patch_with_only_category_pillar_updates_canonical_category(self):
        goal = Goal.objects.create(
            user=self.user,
            title="Patch Pillar Goal",
            description="Initial",
            primary_category="career",
            target_date=timezone.localdate() + timedelta(days=45),
        )

        response = self.client.patch(
            f"/goal/goals/{goal.id}/",
            data={"category_pillar": "Health"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        goal.refresh_from_db()
        self.assertEqual(goal.primary_category, "fitness")
        self.assertEqual(response.data["category_pillar"], "Health")

    def test_payloads_include_category_pillar_for_list_detail_seed_and_hierarchy(self):
        goal = Goal.objects.create(
            user=self.user,
            title="Payload Pillar Goal",
            description="Payload checks",
            primary_category="relationships",
            status="in_progress",
            target_date=timezone.localdate() + timedelta(days=60),
        )

        list_response = self.client.get("/goal/goals/")
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(list_response.data["goals"][0]["category_pillar"], "Relationships")

        detail_response = self.client.get(f"/goal/goals/{goal.id}/")
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_response.data["goal"]["category_pillar"], "Relationships")

        hierarchy_response = self.client.get(f"/goal/goals/{goal.id}/hierarchy/")
        self.assertEqual(hierarchy_response.status_code, status.HTTP_200_OK)
        self.assertEqual(hierarchy_response.data["goal"]["category_pillar"], "Relationships")

        seed_payload = build_goal_seed_data(goal)
        self.assertEqual(seed_payload["category_pillar"], "Relationships")


class GoalCategoryMigrationTests(TransactionTestCase):
    migrate_from = ("goal", "0013_rename_goal_commitm_user_id_ef18db_idx_goal_commit_user_id_ba780e_idx")
    migrate_to = ("goal", "0014_normalize_legacy_goal_categories")

    def setUp(self):
        super().setUp()
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_from])

        old_apps = self.executor.loader.project_state([self.migrate_from]).apps
        User = old_apps.get_model("authentication", "CustomUser")
        Goal = old_apps.get_model("goal", "Goal")
        user = User.objects.create(email="migration-goal@test.com", username="migration-goal@test.com")
        Goal.objects.create(user=user, title="Legacy Financial", primary_category="financial")
        Goal.objects.create(user=user, title="Legacy Health", primary_category="health")
        Goal.objects.create(user=user, title="Legacy Personal", primary_category="personal")
        Goal.objects.create(user=user, title="Canonical Career", primary_category="career")

    def test_migration_normalizes_legacy_categories(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_to])
        apps = self.executor.loader.project_state([self.migrate_to]).apps
        Goal = apps.get_model("goal", "Goal")

        categories = {
            goal.title: goal.primary_category
            for goal in Goal.objects.all()
        }

        self.assertEqual(categories["Legacy Financial"], "finance")
        self.assertEqual(categories["Legacy Health"], "fitness")
        self.assertEqual(categories["Legacy Personal"], "productivity")
        self.assertEqual(categories["Canonical Career"], "career")


TEMP_MEDIA_ROOT = tempfile.mkdtemp(prefix="goal_illustration_test_media_")


@override_settings(MEDIA_ROOT=TEMP_MEDIA_ROOT)
class GoalIllustrationContractTests(APITestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="goal-illustration@test.com",
            password="Password@123",
        )
        self.client.force_authenticate(self.user)
        self.goal = Goal.objects.create(
            user=self.user,
            title="Illustration Goal",
            description="Test illustration status handling.",
            primary_category="career",
            target_date=timezone.localdate() + timedelta(days=30),
        )
        self.illustration_url = f"/goal/goals/{self.goal.id}/illustration/"

    def test_upload_succeeds_with_valid_png(self):
        image = SimpleUploadedFile("illustration.png", b"png-content", content_type="image/png")

        response = self.client.post(self.illustration_url, data={"image": image}, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.goal.refresh_from_db()
        self.assertEqual(self.goal.illustration_status, "done")
        self.assertTrue(self.goal.illustration_url)
        stored_path = self.goal.illustration_url.split("/media/", 1)[1]
        self.assertTrue(default_storage.exists(stored_path))

    def test_upload_rejects_missing_file(self):
        response = self.client.post(self.illustration_url, data={}, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["image"][0], "Please upload an image file.")

    def test_upload_rejects_invalid_file_type(self):
        image = SimpleUploadedFile("illustration.gif", b"gif-content", content_type="image/gif")

        response = self.client.post(self.illustration_url, data={"image": image}, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["image"][0], "Please upload a JPG, PNG, or WebP image.")

    def test_upload_rejects_oversized_file(self):
        image = SimpleUploadedFile(
            "illustration.png",
            b"a" * (5 * 1024 * 1024 + 1),
            content_type="image/png",
        )

        response = self.client.post(self.illustration_url, data={"image": image}, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["image"][0], "Please upload an image smaller than 5 MB.")

    def test_upload_replaces_previous_local_file(self):
        first_image = SimpleUploadedFile("first.png", b"first", content_type="image/png")
        second_image = SimpleUploadedFile("second.png", b"second", content_type="image/png")

        first_response = self.client.post(self.illustration_url, data={"image": first_image}, format="multipart")
        self.assertEqual(first_response.status_code, status.HTTP_200_OK)
        self.goal.refresh_from_db()
        first_path = self.goal.illustration_url.split("/media/", 1)[1]
        self.assertTrue(default_storage.exists(first_path))

        second_response = self.client.post(self.illustration_url, data={"image": second_image}, format="multipart")

        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        self.goal.refresh_from_db()
        second_path = self.goal.illustration_url.split("/media/", 1)[1]
        self.assertNotEqual(first_path, second_path)
        self.assertFalse(default_storage.exists(first_path))
        self.assertTrue(default_storage.exists(second_path))

    def test_delete_clears_image_and_file(self):
        image = SimpleUploadedFile("illustration.png", b"png-content", content_type="image/png")
        upload_response = self.client.post(self.illustration_url, data={"image": image}, format="multipart")
        self.assertEqual(upload_response.status_code, status.HTTP_200_OK)

        self.goal.refresh_from_db()
        stored_path = self.goal.illustration_url.split("/media/", 1)[1]

        response = self.client.delete(self.illustration_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.goal.refresh_from_db()
        self.assertEqual(self.goal.illustration_status, "pending")
        self.assertIsNone(self.goal.illustration_url)
        self.assertFalse(default_storage.exists(stored_path))
