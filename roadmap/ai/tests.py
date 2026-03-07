import os
from datetime import timedelta
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch, MagicMock
import httpx

from rest_framework import status
from rest_framework.test import APITestCase

from authentication.models import NotificationSettings
from ai.models import AIReengagementAction, AIUserChurnState
from ai.providers.ollama_provider import OllamaProvider
from ai.services.churn_reengagement import ChurnReengagementService
from goal.models import Goal, Milestone
from ai.utils.validators import OutputValidator


class HierarchyQualityAssessmentTests(TestCase):
    def test_assess_hierarchy_quality_returns_scores_and_detects_issues(self):
        hierarchy = {
            "milestones": [
                {
                    "subgoals": [
                        {
                            "subgoal_data": {"week_number": 2},
                            "tasks": [
                                {
                                    "title": "Learn stuff",
                                    "description": "Short",
                                    "task_type": "learning",
                                    "estimated_duration_minutes": 300,
                                }
                            ],
                        },
                        {
                            "subgoal_data": {"week_number": 1},
                            "tasks": [
                                {
                                    "title": "Practice feature implementation",
                                    "description": "Implement and validate one concrete feature using test data.",
                                    "task_type": "practice",
                                    "estimated_duration_minutes": 90,
                                }
                            ],
                        },
                    ]
                }
            ]
        }

        report = OutputValidator.assess_hierarchy_quality(
            hierarchy=hierarchy,
            timeline_days=2,
            experience_level="beginner",
            constraints=["limited time"],
        )

        self.assertIn("overall_score", report)
        self.assertIn("issues", report)
        self.assertLess(report["sequencing_score"], 100)
        self.assertGreater(len(report["issues"]), 0)


class GenerateMilestonesOwnershipTests(APITestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.owner = self.user_model.objects.create_user(
            email="owner@example.com",
            password="testpass123",
        )
        self.other_user = self.user_model.objects.create_user(
            email="other@example.com",
            password="testpass123",
        )
        self.goal = Goal.objects.create(
            user=self.owner,
            title="Owner Goal",
            primary_category="career",
        )
        self.url = reverse(
            "generate-milestones",
            kwargs={"goal_id": self.goal.id},
        )

    @patch("ai.views.GoalHierarchyGenerator.generate_complete_hierarchy")
    def test_generate_milestones_denies_non_owner_goal_access(self, mock_generate):
        self.client.force_authenticate(user=self.other_user)

        response = self.client.post(self.url, data={}, format="json")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        mock_generate.assert_not_called()

    @patch("ai.views.GoalHierarchyGenerator.generate_complete_hierarchy")
    def test_generate_milestones_allows_goal_owner(self, mock_generate):
        self.client.force_authenticate(user=self.owner)
        mock_generate.return_value = {
            "status": "success",
            "message": "Milestones generated",
            "data": {"milestones": []},
            "job_id": "abc-123",
        }

        response = self.client.post(self.url, data={}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "success")
        mock_generate.assert_called_once()


class AIEndpointContractTests(APITestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.user = self.user_model.objects.create_user(
            email="contract@example.com",
            password="testpass123",
        )
        self.goal = Goal.objects.create(
            user=self.user,
            title="Contract Goal",
            primary_category="career",
        )
        self.client.force_authenticate(user=self.user)

    def test_ai_root_returns_contract_payload(self):
        response = self.client.get(reverse("ai-api"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "ok")
        self.assertIn("endpoints", response.data)

    def test_goal_attribute_extractor_requires_goal_id(self):
        response = self.client.post(
            reverse("goal-attribute-extractor"),
            data={"user_input": "I want to improve in my career."},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["status"], "error")
        self.assertEqual(response.data["message"], "goal_id is required")

    @patch("ai.views.GoalAttributeExtractor.extract_goal_attributes")
    def test_goal_attribute_extractor_returns_service_error_contract(self, mock_extract):
        mock_extract.return_value = {
            "status": "error",
            "message": "Extraction failed",
            "job_id": "job-1",
        }
        response = self.client.post(
            reverse("goal-attribute-extractor"),
            data={"user_input": "Some goal text", "goal_id": str(self.goal.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["status"], "error")
        self.assertEqual(response.data["message"], "Extraction failed")
        self.assertEqual(response.data["job_id"], "job-1")

    def test_generate_milestones_get_returns_non_stub_contract(self):
        response = self.client.get(
            reverse("generate-milestones", kwargs={"goal_id": self.goal.id})
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "ok")
        self.assertEqual(response.data["goal_id"], str(self.goal.id))
        self.assertEqual(response.data["milestone_count"], 0)
        self.assertTrue(response.data["can_generate"])

    def test_generate_milestones_get_reports_existing_milestones(self):
        Milestone.objects.create(
            goal=self.goal,
            title="Existing Milestone",
            display_order=1,
            priority="medium",
        )
        response = self.client.get(
            reverse("generate-milestones", kwargs={"goal_id": self.goal.id})
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "ok")
        self.assertEqual(response.data["milestone_count"], 1)
        self.assertFalse(response.data["can_generate"])


class AIExplicitExceptionHandlingTests(APITestCase):
    def setUp(self):
        os.environ["OLLAMA_HOST"] = "http://localhost:11434"
        os.environ["OLLAMA_MODEL"] = "test-model"
        self.user_model = get_user_model()
        self.user = self.user_model.objects.create_user(
            email="ai-explicit@test.com",
            password="testpass123",
        )
        self.client.force_authenticate(user=self.user)

    @patch("ai.views.CurrentSituationGenerator.generate")
    def test_process_current_situation_handles_invalid_payload_type_error(self, mock_generate):
        mock_generate.return_value = {"data": None, "job_id": "abc-123"}

        response = self.client.post(
            reverse("ai-process-text-data-current-situation"),
            data={"raw_data": "I am currently stuck and need help."},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "Invalid AI response payload")

    @patch("ai.views.OllamaProvider.health_check", side_effect=OSError("provider unavailable"))
    def test_health_check_handles_provider_os_error(self, _mock_health):
        response = self.client.get(reverse("ai-health-check"))

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data["status"], "unhealthy")
        self.assertEqual(response.data["service"], "ollama")


class OllamaProviderEnvConfigTests(TestCase):
    @patch("ai.providers.ollama_provider.Client")
    def test_provider_requires_ollama_host_env_when_host_is_not_passed(self, _mock_client):
        with patch.dict(os.environ, {"OLLAMA_HOST": "", "OLLAMA_MODEL": "demo-model"}, clear=False):
            with self.assertRaises(ImproperlyConfigured):
                OllamaProvider()

    @patch("ai.providers.ollama_provider.Client")
    def test_provider_uses_default_model_when_model_env_is_not_passed(self, mock_client):
        with patch.dict(os.environ, {"OLLAMA_HOST": "http://localhost:11434", "OLLAMA_MODEL": ""}, clear=False):
            provider = OllamaProvider()

        mock_client.assert_called_once()
        called_kwargs = mock_client.call_args.kwargs
        self.assertEqual(called_kwargs["host"], "http://localhost:11434")
        self.assertEqual(called_kwargs["timeout"], 180.0)
        self.assertFalse(called_kwargs["trust_env"])
        self.assertEqual(provider.model, "gpt-oss:120b-cloud")

    @patch("ai.providers.ollama_provider.Client")
    def test_provider_allows_explicit_host_and_model_overrides(self, mock_client):
        with patch.dict(os.environ, {"OLLAMA_HOST": "", "OLLAMA_MODEL": ""}, clear=False):
            provider = OllamaProvider(host="http://custom-host:11434", model="custom-model")

        mock_client.assert_called_once()
        called_kwargs = mock_client.call_args.kwargs
        self.assertEqual(called_kwargs["host"], "http://custom-host:11434")
        self.assertEqual(called_kwargs["timeout"], 180.0)
        self.assertFalse(called_kwargs["trust_env"])
        self.assertEqual(provider.host, "http://custom-host:11434")
        self.assertEqual(provider.model, "custom-model")

    @patch("ai.providers.ollama_provider.Client")
    def test_provider_respects_ollama_transport_env_overrides(self, mock_client):
        with patch.dict(
            os.environ,
            {
                "OLLAMA_HOST": "http://localhost:11434",
                "OLLAMA_MODEL": "demo-model",
                "OLLAMA_REQUEST_TIMEOUT_SECONDS": "42",
                "OLLAMA_TRUST_ENV": "true",
            },
            clear=False,
        ):
            OllamaProvider()

        called_kwargs = mock_client.call_args.kwargs
        self.assertEqual(called_kwargs["timeout"], 42.0)
        self.assertTrue(called_kwargs["trust_env"])


class OllamaProviderRetryTests(TestCase):
    def setUp(self):
        self.env = {
            "OLLAMA_HOST": "http://localhost:11434",
            "OLLAMA_MODEL": "demo-model",
            "OLLAMA_MAX_RETRIES": "2",
            "OLLAMA_RETRY_BACKOFF_SECONDS": "0",
        }

    @patch("ai.providers.ollama_provider.time.sleep")
    @patch("ai.providers.ollama_provider.Client")
    def test_generate_response_retries_on_read_error_and_succeeds(self, mock_client, _mock_sleep):
        first_client = MagicMock()
        second_client = MagicMock()
        third_client = MagicMock()
        first_client.chat.side_effect = httpx.ReadError("winerror 10054")
        second_client.chat.side_effect = httpx.ReadError("connection reset by peer")
        third_client.chat.return_value = {"message": {"content": "ok"}}
        mock_client.side_effect = [first_client, second_client, third_client]

        with patch.dict(os.environ, self.env, clear=False):
            provider = OllamaProvider()
            response = provider.generate_response(prompt="hello")

        self.assertEqual(response.content, "ok")
        self.assertEqual(mock_client.call_count, 3)

    @patch("ai.providers.ollama_provider.time.sleep")
    @patch("ai.providers.ollama_provider.Client")
    def test_generate_response_raises_after_retry_budget_exhausted(self, mock_client, _mock_sleep):
        first_client = MagicMock()
        second_client = MagicMock()
        third_client = MagicMock()
        first_client.chat.side_effect = httpx.ReadError("winerror 10054")
        second_client.chat.side_effect = httpx.ReadError("winerror 10054")
        third_client.chat.side_effect = httpx.ReadError("winerror 10054")
        mock_client.side_effect = [first_client, second_client, third_client]

        with patch.dict(os.environ, self.env, clear=False):
            provider = OllamaProvider()
            with self.assertRaises(RuntimeError) as exc:
                provider.generate_response(prompt="hello")

        self.assertIn("Ollama generation failed", str(exc.exception))
        self.assertEqual(mock_client.call_count, 3)


class AIHealthCheckConfigTests(APITestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.user = self.user_model.objects.create_user(
            email="ai-health-config@test.com",
            password="testpass123",
        )
        self.client.force_authenticate(user=self.user)

    def test_health_check_returns_unhealthy_when_required_env_is_missing(self):
        with patch.dict(os.environ, {"OLLAMA_HOST": "", "OLLAMA_MODEL": ""}, clear=False):
            response = self.client.get(reverse("ai-health-check"))

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data["status"], "unhealthy")
        self.assertEqual(response.data["service"], "ollama")
        self.assertIn("Missing required environment variable", response.data["error"])

    @patch("ai.views.OllamaProvider.health_check", autospec=True)
    def test_health_check_uses_default_model_when_ollama_model_is_missing(self, mock_health_check):
        def _healthy(provider_instance):
            return {
                "status": "healthy",
                "service": "ollama",
                "host": provider_instance.host,
                "model": provider_instance.model,
                "error": None,
            }

        mock_health_check.side_effect = _healthy

        with patch.dict(
            os.environ,
            {"OLLAMA_HOST": "http://localhost:11434", "OLLAMA_MODEL": ""},
            clear=False,
        ):
            response = self.client.get(reverse("ai-health-check"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "healthy")
        self.assertEqual(response.data["service"], "ollama")
        self.assertEqual(response.data["model"], "gpt-oss:120b-cloud")


class ChurnReengagementServiceTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.user = self.user_model.objects.create_user(
            email="churn-service@test.com",
            password="testpass123",
        )
        self.service = ChurnReengagementService()

    def test_tier_boundaries(self):
        self.assertEqual(self.service._tier_for_score(39.9), AIUserChurnState.RISK_TIER_LOW)
        self.assertEqual(self.service._tier_for_score(40.0), AIUserChurnState.RISK_TIER_MEDIUM)
        self.assertEqual(self.service._tier_for_score(69.9), AIUserChurnState.RISK_TIER_MEDIUM)
        self.assertEqual(self.service._tier_for_score(70.0), AIUserChurnState.RISK_TIER_HIGH)

    def test_score_user_high_risk_when_no_activity(self):
        result = self.service.score_user(user=self.user)

        self.assertGreaterEqual(result.risk_score, 90.0)
        self.assertEqual(result.risk_tier, AIUserChurnState.RISK_TIER_HIGH)
        self.assertGreaterEqual(result.inactivity_days, 300)

    def test_notification_gating_suppresses_action_when_disabled(self):
        NotificationSettings.objects.update_or_create(
            user=self.user,
            defaults={
                "notifications_enabled": False,
                "personalize_assistant": True,
                "push_notifications": True,
                "email_notifications": True,
            },
        )

        result = self.service.process_user(user=self.user)
        self.assertEqual(result["status"], AIReengagementAction.STATUS_SUPPRESSED)

        latest = AIReengagementAction.objects.filter(user=self.user).first()
        self.assertIsNotNone(latest)
        self.assertEqual(latest.reason_code, "notifications_disabled")

    @patch("ai.services.churn_reengagement.ChurnReengagementService.score_user")
    def test_cooldown_blocks_duplicate_action_within_24h(self, mock_score_user):
        NotificationSettings.objects.update_or_create(
            user=self.user,
            defaults={
                "notifications_enabled": True,
                "personalize_assistant": True,
                "push_notifications": True,
                "email_notifications": False,
            },
        )
        mock_score_user.return_value = type(
            "ScoreResult",
            (),
            {
                "risk_score": 50.0,
                "risk_tier": AIUserChurnState.RISK_TIER_MEDIUM,
                "inactivity_days": 4,
                "last_activity_at": timezone.now() - timedelta(days=4),
                "score_inputs": {},
            },
        )()

        first = self.service.process_user(user=self.user)
        second = self.service.process_user(user=self.user)

        self.assertEqual(first["status"], AIReengagementAction.STATUS_SENT)
        self.assertEqual(second["status"], AIReengagementAction.STATUS_COOLDOWN_BLOCKED)

    @patch("ai.services.churn_reengagement.ChurnReengagementService._get_last_activity_at")
    @patch("ai.services.churn_reengagement.ChurnReengagementService.score_user")
    def test_reengaged_user_is_blocked(self, mock_score_user, mock_last_activity):
        NotificationSettings.objects.update_or_create(
            user=self.user,
            defaults={
                "notifications_enabled": True,
                "personalize_assistant": True,
                "push_notifications": True,
                "email_notifications": False,
            },
        )
        mock_score_user.return_value = type(
            "ScoreResult",
            (),
            {
                "risk_score": 85.0,
                "risk_tier": AIUserChurnState.RISK_TIER_HIGH,
                "inactivity_days": 8,
                "last_activity_at": timezone.now() - timedelta(days=8),
                "score_inputs": {},
            },
        )()
        mock_last_activity.return_value = timezone.now()

        result = self.service.process_user(user=self.user)

        self.assertEqual(result["status"], AIReengagementAction.STATUS_REENGAGED_BLOCKED)

    def test_high_tier_escalates_after_prior_nudge(self):
        NotificationSettings.objects.update_or_create(
            user=self.user,
            defaults={
                "notifications_enabled": True,
                "personalize_assistant": True,
                "push_notifications": True,
                "email_notifications": False,
            },
        )

        churn_state = AIUserChurnState.objects.create(
            user=self.user,
            risk_score=85.0,
            risk_tier=AIUserChurnState.RISK_TIER_HIGH,
            inactivity_days=10,
            score_inputs={},
        )
        AIReengagementAction.objects.create(
            user=self.user,
            churn_state=churn_state,
            action_type=AIReengagementAction.ACTION_TYPE_NUDGE,
            channel=AIReengagementAction.CHANNEL_PUSH,
            status=AIReengagementAction.STATUS_SENT,
            reason_code="delivered",
            risk_score=70.0,
            risk_tier=AIUserChurnState.RISK_TIER_HIGH,
            metadata={},
        )

        # Make the prior nudge old enough so cooldown does not block escalation.
        AIReengagementAction.objects.filter(user=self.user).update(
            created_at=timezone.now() - timedelta(hours=25)
        )

        result = self.service.process_user(user=self.user)
        self.assertEqual(result["status"], AIReengagementAction.STATUS_SENT)

        latest = AIReengagementAction.objects.filter(user=self.user).order_by("-created_at").first()
        self.assertEqual(latest.action_type, AIReengagementAction.ACTION_TYPE_ESCALATION)

    @patch("ai.services.churn_reengagement.ChurnReengagementService.score_user")
    def test_sent_push_action_includes_message_payload_metadata(self, mock_score_user):
        NotificationSettings.objects.update_or_create(
            user=self.user,
            defaults={
                "notifications_enabled": True,
                "personalize_assistant": True,
                "push_notifications": True,
                "email_notifications": False,
            },
        )
        mock_score_user.return_value = type(
            "ScoreResult",
            (),
            {
                "risk_score": 55.0,
                "risk_tier": AIUserChurnState.RISK_TIER_MEDIUM,
                "inactivity_days": 4,
                "last_activity_at": timezone.now() - timedelta(days=4),
                "score_inputs": {},
            },
        )()

        result = self.service.process_user(user=self.user)
        self.assertEqual(result["status"], AIReengagementAction.STATUS_SENT)

        action = AIReengagementAction.objects.filter(user=self.user).order_by("-created_at").first()
        payload = action.metadata.get("message_payload", {})

        self.assertEqual(action.channel, AIReengagementAction.CHANNEL_PUSH)
        self.assertEqual(payload.get("channel"), AIReengagementAction.CHANNEL_PUSH)
        self.assertEqual(payload.get("action_type"), AIReengagementAction.ACTION_TYPE_NUDGE)
        self.assertTrue(payload.get("headline"))
        self.assertTrue(payload.get("body"))
        self.assertEqual(payload.get("cta", {}).get("target"), "/routine")

    @patch("ai.services.churn_reengagement.ChurnReengagementService.score_user")
    def test_sent_email_action_includes_message_payload_metadata(self, mock_score_user):
        NotificationSettings.objects.update_or_create(
            user=self.user,
            defaults={
                "notifications_enabled": True,
                "personalize_assistant": True,
                "push_notifications": False,
                "email_notifications": True,
            },
        )
        mock_score_user.return_value = type(
            "ScoreResult",
            (),
            {
                "risk_score": 58.0,
                "risk_tier": AIUserChurnState.RISK_TIER_MEDIUM,
                "inactivity_days": 5,
                "last_activity_at": timezone.now() - timedelta(days=5),
                "score_inputs": {},
            },
        )()

        result = self.service.process_user(user=self.user)
        self.assertEqual(result["status"], AIReengagementAction.STATUS_SENT)

        action = AIReengagementAction.objects.filter(user=self.user).order_by("-created_at").first()
        payload = action.metadata.get("message_payload", {})

        self.assertEqual(action.channel, AIReengagementAction.CHANNEL_EMAIL)
        self.assertEqual(payload.get("channel"), AIReengagementAction.CHANNEL_EMAIL)
        self.assertEqual(payload.get("risk_tier"), AIUserChurnState.RISK_TIER_MEDIUM)
        self.assertTrue(payload.get("headline"))
        self.assertTrue(payload.get("body"))


class ChurnReengagementCommandTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.user = self.user_model.objects.create_user(
            email="churn-command@test.com",
            password="testpass123",
        )
        NotificationSettings.objects.update_or_create(
            user=self.user,
            defaults={
                "notifications_enabled": True,
                "personalize_assistant": True,
                "push_notifications": True,
                "email_notifications": False,
            },
        )

    def test_management_command_processes_user_and_persists_records(self):
        call_command("run_churn_reengagement")

        self.assertTrue(AIUserChurnState.objects.filter(user=self.user).exists())
        self.assertTrue(AIReengagementAction.objects.filter(user=self.user).exists())
