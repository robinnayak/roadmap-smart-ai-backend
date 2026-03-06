import os
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse
from unittest.mock import patch, MagicMock
import httpx

from rest_framework import status
from rest_framework.test import APITestCase

from ai.providers.ollama_provider import OllamaProvider
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
