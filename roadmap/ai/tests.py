import os
from pathlib import Path
from decimal import Decimal
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
from ai.config import (
    get_fallback_routes,
    get_missing_ai_env_vars,
    get_model_for_task,
    get_model_id,
    get_provider_routes,
)
from ai.models import AIModelUsageStats, AIProcessingJob, AIReengagementAction, AIUserChurnState
from ai.providers.base import AIResponse
from ai.providers.ollama_provider import OllamaProvider
from ai.providers.router import RoutedAIProvider
from ai.prompts.GoalHierarchyGeneratorPrompts import GoalHierarchyGeneratorPrompts, _load
from ai.services.GoalHierarchyGenerator import GoalHierarchyGenerator
from ai.services.churn_reengagement import ChurnReengagementService
from ai.services.current_situation_generator import CurrentSituationGenerationError, CurrentSituationGenerator
from goal.models import Goal, GoalAttributes, Milestone
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


class PromptAssetTests(TestCase):
    def test_prompt_assets_exist_and_are_utf8_readable(self):
        prompts_dir = Path(__file__).resolve().parent / "prompts"
        txt_files = sorted(prompts_dir.rglob("*.txt"))
        self.assertGreater(len(txt_files), 0)
        for path in txt_files:
            content = path.read_text(encoding="utf-8")
            self.assertTrue(content.strip(), msg=f"{path} should not be empty")

    def test_shared_prompt_assets_exist(self):
        prompts_dir = Path(__file__).resolve().parent / "prompts"
        self.assertTrue((prompts_dir / "shared" / "base_rules.txt").exists())
        self.assertTrue((prompts_dir / "shared" / "task_type_schema.txt").exists())

    def test_shared_base_rules_include_all_required_rules(self):
        prompts_dir = Path(__file__).resolve().parent / "prompts"
        base_rules = (prompts_dir / "shared" / "base_rules.txt").read_text(encoding="utf-8")
        for marker in (
            "RULE 1 · ACTION-FIRST TITLES",
            "RULE 2 · SPECIFIC COMPLETION SIGNAL",
            "RULE 3 · DESCRIPTIONS ARE INSTRUCTIONS, NOT EXPLANATIONS",
            "RULE 4 · NO FILLER TASKS",
            "RULE 5 · RATIONALE IS PERSONAL",
            "RULE 6 · MATCH THE CATEGORY ACTION STYLE",
        ):
            self.assertIn(marker, base_rules)

    def test_shared_task_type_schema_includes_all_valid_types_and_decision_tree(self):
        prompts_dir = Path(__file__).resolve().parent / "prompts"
        type_schema = (prompts_dir / "shared" / "task_type_schema.txt").read_text(encoding="utf-8")
        self.assertIn("There are exactly five valid task types.", type_schema)
        for marker in (
            "TYPE: physical",
            "TYPE: cognitive",
            "TYPE: habit",
            "TYPE: ritual",
            "TYPE: task",
            "TYPE ASSIGNMENT DECISION TREE",
        ):
            self.assertIn(marker, type_schema)

    def test_goal_task_prompt_assets_include_required_contract_markers(self):
        prompts_dir = Path(__file__).resolve().parent / "prompts"
        system_path = prompts_dir / "goal_task" / "system.txt"
        output_schema_path = prompts_dir / "goal_task" / "output_schema.txt"
        self.assertTrue(system_path.exists())
        self.assertTrue(output_schema_path.exists())

        system_text = system_path.read_text(encoding="utf-8")
        output_schema = output_schema_path.read_text(encoding="utf-8")

        self.assertIn("SYSTEM: SUBGOAL TASK GENERATION ENGINE", system_text)
        self.assertIn("Return valid JSON with a single top-level \"tasks\" array.", system_text)
        self.assertIn("Use only valid item_type values: physical, cognitive, habit, ritual, task.", system_text)

        self.assertIn('"item_type": "physical | cognitive | habit | ritual | task"', output_schema)
        self.assertIn("VALIDATION RULES", output_schema)
        self.assertIn('"tasks": [', output_schema)
        self.assertIn("Ensure titles are unique within this array.", output_schema)


class LLMRoutingConfigTests(TestCase):
    def test_get_model_id_resolves_generic_keys_per_provider(self):
        self.assertEqual(get_model_id("GPT_OSS_120B", "ollama"), "gpt-oss:120b-cloud")
        self.assertEqual(get_model_id("GPT_OSS_120B", "groq"), "openai/gpt-oss-120b")
        self.assertEqual(get_model_id("GPT_OSS_120B", "openrouter"), "openai/gpt-oss-120b")
        self.assertEqual(get_model_id("LLAMA_3_3_70B", "groq"), "llama-3.3-70b-versatile")
        self.assertEqual(
            get_model_id("LLAMA_3_3_70B", "openrouter"),
            "meta-llama/llama-3.3-70b-instruct",
        )

    def test_get_model_id_passthrough_for_unknown_key(self):
        self.assertEqual(get_model_id("custom/provider-model", "groq"), "custom/provider-model")

    def test_get_model_id_retargets_known_provider_specific_ids(self):
        self.assertEqual(get_model_id("gpt-oss:120b-cloud", "groq"), "openai/gpt-oss-120b")
        self.assertEqual(
            get_model_id("meta-llama/llama-3.3-70b-instruct", "ollama"),
            "llama3.3:70b",
        )

    def test_get_model_for_task_resolves_generic_key_for_provider(self):
        with patch.dict(
            os.environ,
            {
                "DEBUG": "false",
                "LLM_PRIMARY_PROVIDER": "groq",
                "HIERARCHY_MODEL": "GPT_OSS_120B",
            },
            clear=False,
        ):
            groq_model = get_model_for_task("goal_hierarchy", "groq")
            ollama_model = get_model_for_task("goal_hierarchy", "ollama")

        self.assertEqual(groq_model, "openai/gpt-oss-120b")
        self.assertEqual(ollama_model, "gpt-oss:120b-cloud")

    def test_provider_routes_use_env_primary_and_fallbacks(self):
        with patch.dict(
            os.environ,
            {
                "DEBUG": "false",
                "LLM_PRIMARY_PROVIDER": "groq",
                "HIERARCHY_MODEL": "hierarchy-model",
                "LLM_FALLBACKS": "openrouter:router-model,ollama:local-model",
            },
            clear=False,
        ):
            routes = get_provider_routes(task_name="goal_hierarchy")

        self.assertEqual(routes[0].provider_name, "groq")
        self.assertEqual(routes[0].model, "hierarchy-model")
        self.assertEqual(routes[1].provider_name, "openrouter")
        self.assertEqual(routes[1].model, "router-model")
        self.assertEqual(routes[2].provider_name, "ollama")
        self.assertEqual(routes[2].model, "local-model")

    def test_provider_routes_retarget_known_provider_specific_primary_override(self):
        with patch.dict(
            os.environ,
            {
                "DEBUG": "false",
                "LLM_PRIMARY_PROVIDER": "groq",
                "HIERARCHY_MODEL": "gpt-oss:120b-cloud",
            },
            clear=False,
        ):
            routes = get_provider_routes(task_name="goal_hierarchy")

        self.assertEqual(routes[0].provider_name, "groq")
        self.assertEqual(routes[0].model, "openai/gpt-oss-120b")

    def test_fallback_routes_support_generic_model_keys(self):
        with patch.dict(
            os.environ,
            {
                "DEBUG": "false",
                "LLM_PRIMARY_PROVIDER": "groq",
                "LLM_FALLBACKS": "openrouter:LLAMA_3_3_70B,ollama:GPT_OSS_120B",
            },
            clear=False,
        ):
            routes = get_fallback_routes("goal_hierarchy")

        self.assertEqual(routes[0].provider_name, "openrouter")
        self.assertEqual(routes[0].model, "meta-llama/llama-3.3-70b-instruct")
        self.assertEqual(routes[1].provider_name, "ollama")
        self.assertEqual(routes[1].model, "gpt-oss:120b-cloud")

    def test_provider_routes_resolve_generic_primary_and_fallback_models(self):
        with patch.dict(
            os.environ,
            {
                "DEBUG": "false",
                "LLM_PRIMARY_PROVIDER": "groq",
                "HIERARCHY_MODEL": "GPT_OSS_120B",
                "LLM_FALLBACKS": "openrouter:LLAMA_3_3_70B,ollama:GPT_OSS_120B",
            },
            clear=False,
        ):
            routes = get_provider_routes(task_name="goal_hierarchy")

        self.assertEqual(routes[0].provider_name, "groq")
        self.assertEqual(routes[0].model, "openai/gpt-oss-120b")
        self.assertEqual(routes[1].provider_name, "openrouter")
        self.assertEqual(routes[1].model, "meta-llama/llama-3.3-70b-instruct")
        self.assertEqual(routes[2].provider_name, "ollama")
        self.assertEqual(routes[2].model, "gpt-oss:120b-cloud")

    def test_routed_provider_passes_provider_specific_model_to_provider_instance(self):
        constructed_models = []

        class RecordingProvider:
            def __init__(self, model=None, temperature=0.7, max_tokens=None, stream=False):
                self.model = model
                constructed_models.append(model)

            def generate_response(self, prompt, system_prompt=None, context=None):
                return AIResponse(content="ok", model=self.model)

            def health_check(self):
                return {"status": "healthy", "model": self.model}

        with patch.dict(
            os.environ,
            {
                "DEBUG": "false",
                "LLM_PRIMARY_PROVIDER": "groq",
                "HIERARCHY_MODEL": "GPT_OSS_120B",
            },
            clear=False,
        ), patch.dict(
            "ai.providers.router.PROVIDER_CLASS_MAP",
            {"groq": RecordingProvider, "openrouter": RecordingProvider, "ollama": RecordingProvider},
            clear=True,
        ):
            provider = RoutedAIProvider(task_name="goal_hierarchy")
            response = provider.generate_response(prompt="hello")

        self.assertEqual(constructed_models, ["openai/gpt-oss-120b"])
        self.assertEqual(response.model, "openai/gpt-oss-120b")

    def test_routed_provider_retries_next_route_when_response_content_is_empty(self):
        attempts = []

        class EmptyProvider:
            def __init__(self, model=None, temperature=0.7, max_tokens=None, stream=False):
                self.model = model

            def generate_response(self, prompt, system_prompt=None, context=None):
                attempts.append(("groq", self.model))
                return AIResponse(content="", model=self.model)

            def health_check(self):
                return {"status": "healthy", "model": self.model}

        class SuccessProvider:
            def __init__(self, model=None, temperature=0.7, max_tokens=None, stream=False):
                self.model = model

            def generate_response(self, prompt, system_prompt=None, context=None):
                attempts.append(("openrouter", self.model))
                return AIResponse(content='{"tasks":[]}', model=self.model)

            def health_check(self):
                return {"status": "healthy", "model": self.model}

        with patch.dict(
            os.environ,
            {
                "DEBUG": "false",
                "LLM_PRIMARY_PROVIDER": "groq",
                "HIERARCHY_MODEL": "GPT_OSS_120B",
                "LLM_FALLBACKS": "openrouter:LLAMA_3_3_70B",
            },
            clear=False,
        ), patch.dict(
            "ai.providers.router.PROVIDER_CLASS_MAP",
            {"groq": EmptyProvider, "openrouter": SuccessProvider, "ollama": SuccessProvider},
            clear=True,
        ):
            provider = RoutedAIProvider(task_name="goal_hierarchy")
            response = provider.generate_response(prompt="hello")

        self.assertEqual(
            attempts,
            [
                ("groq", "openai/gpt-oss-120b"),
                ("openrouter", "meta-llama/llama-3.3-70b-instruct"),
            ],
        )
        self.assertEqual(response.content, '{"tasks":[]}')

    def test_missing_ai_env_vars_accepts_fallback_provider(self):
        with patch.dict(
            os.environ,
            {
                "DEBUG": "false",
                "LLM_PRIMARY_PROVIDER": "groq",
                "GROQ_API_KEY": "",
                "OPENROUTER_API_KEY": "router-key",
                "LLM_FALLBACKS": "openrouter:router-model",
            },
            clear=False,
        ):
            missing = get_missing_ai_env_vars(task_name="journeybook")

        self.assertEqual(missing, [])

    def test_all_category_prompt_assets_exist(self):
        prompts_dir = Path(__file__).resolve().parent / "prompts" / "categories"
        expected = {
            "fitness.txt",
            "finance.txt",
            "learning.txt",
            "career.txt",
            "wellness.txt",
            "creative.txt",
            "business.txt",
            "nutrition.txt",
            "relationships.txt",
            "productivity.txt",
            "travel.txt",
            "spiritual.txt",
            "parenting.txt",
            "education.txt",
            "digital_habits.txt",
        }
        actual = {path.name for path in prompts_dir.glob("*.txt")}
        self.assertEqual(actual, expected)

    def test_category_prompt_assets_include_required_markers(self):
        prompts_dir = Path(__file__).resolve().parent / "prompts" / "categories"
        fitness = (prompts_dir / "fitness.txt").read_text(encoding="utf-8")
        self.assertIn("40% physical", fitness)
        self.assertIn("RULES:", fitness)
        self.assertIn("FORBIDDEN:", fitness)

        finance = (prompts_dir / "finance.txt").read_text(encoding="utf-8")
        self.assertIn("35% task", finance)
        self.assertIn("RULES:", finance)
        self.assertIn("FORBIDDEN:", finance)

        business = (prompts_dir / "business.txt").read_text(encoding="utf-8")
        self.assertIn("VALIDATION STAGE: NO BUILD TASKS", business)
        self.assertIn("Generate ZERO build tasks.", business)

        wellness = (prompts_dir / "wellness.txt").read_text(encoding="utf-8")
        self.assertIn("If therapy_active and today is therapy_day:", wellness)

        creative = (prompts_dir / "creative.txt").read_text(encoding="utf-8")
        self.assertIn("ENFORCE NO-EDITING RULE FOR DRAFT SESSIONS", creative)
        self.assertIn("No editing during this session.", creative)

        digital_habits = (prompts_dir / "digital_habits.txt").read_text(encoding="utf-8")
        self.assertIn("REPLACEMENT BEHAVIOUR MUST BE PHYSICALLY PREPARED", digital_habits)


class GoalHierarchyPromptBuilderTests(TestCase):
    def test_task_prompt_builder_assembles_all_six_sections_in_order(self):
        prompt = GoalHierarchyGeneratorPrompts().get_task_generating_prompt(
            subgoal_data={
                "title": "Week 1",
                "description": "Ship first version",
                "week_number": 1,
            },
            milestone_data={
                "id": 11,
                "title": "Month 1",
                "description": "Foundation",
                "success_criteria": ["First release shipped"],
            },
            goal_data={
                "title": "Launch MVP",
                "description": "Build and launch SaaS MVP",
                "primary_category": "personal",
                "resolved_category": "business",
                "why_it_matters": ["Revenue"],
                "target_date": "2026-04-15",
                "available_daily_minutes": 90,
                "user_strengths": ["Shipping quickly"],
                "user_blockers": ["Limited time"],
                "motivation_style": "outcome-driven",
            },
        )

        markers = [
            "SHARED BASE RULES",
            "TASK TYPE DEFINITIONS",
            "SYSTEM: SUBGOAL TASK GENERATION ENGINE",
            "CATEGORY: BUSINESS",
            "USER AND GOAL CONTEXT",
            "OUTPUT — RETURN THIS JSON ONLY",
        ]
        positions = [prompt.index(marker) for marker in markers]
        self.assertEqual(positions, sorted(positions))

    def test_resolved_category_overrides_primary_category(self):
        prompt = GoalHierarchyGeneratorPrompts().get_task_generating_prompt(
            subgoal_data={"title": "Week 1"},
            milestone_data={"title": "Month 1"},
            goal_data={
                "title": "Launch MVP",
                "primary_category": "career",
                "resolved_category": "business",
            },
        )

        self.assertIn("CATEGORY: BUSINESS", prompt)
        self.assertNotIn("CATEGORY: CAREER", prompt)
        self.assertIn("Category: business", prompt)

    def test_primary_category_is_used_when_resolved_category_missing(self):
        prompt = GoalHierarchyGeneratorPrompts().get_task_generating_prompt(
            subgoal_data={"title": "Week 1"},
            milestone_data={"title": "Month 1"},
            goal_data={"title": "Prepare for marathon", "primary_category": "fitness"},
        )

        self.assertIn("CATEGORY: FITNESS", prompt)
        self.assertIn("Category: fitness", prompt)

    def test_unknown_category_falls_back_to_productivity_prompt(self):
        with self.assertLogs("ai.prompts.GoalHierarchyGeneratorPrompts", level="WARNING") as captured:
            prompt = GoalHierarchyGeneratorPrompts().get_task_generating_prompt(
                subgoal_data={"title": "Week 1"},
                milestone_data={"title": "Month 1"},
                goal_data={
                    "title": "Unclear",
                    "primary_category": "personal",
                    "resolved_category": "unknown",
                },
            )

        self.assertIn("CATEGORY: PRODUCTIVITY", prompt)
        self.assertIn("Category: unknown", prompt)
        self.assertTrue(
            any("falling back to 'productivity'" in message for message in captured.output)
        )

    def test_rendered_context_includes_required_goal_milestone_subgoal_and_capacity_fields(self):
        prompt = GoalHierarchyGeneratorPrompts().get_task_generating_prompt(
            subgoal_data={
                "title": "Week 2: Validation",
                "description": "Test onboarding with users",
                "week_number": 2,
            },
            milestone_data={
                "id": 23,
                "title": "Month 1: MVP foundation",
                "description": "Build the first usable version",
                "success_criteria": ["Working auth", "Usable onboarding"],
            },
            goal_data={
                "title": "Launch MVP",
                "primary_category": "personal",
                "resolved_category": "business",
                "description": "Build and ship a usable MVP",
                "why_it_matters": ["Revenue", "Momentum"],
                "target_date": "2026-05-01",
                "available_daily_minutes": 75,
                "user_strengths": ["Fast iteration"],
                "user_blockers": ["Day job"],
                "motivation_style": "intrinsic",
            },
        )

        for expected in (
            "Title: Launch MVP",
            "Category: business",
            "Description: Build and ship a usable MVP",
            "Why It Matters: Revenue, Momentum",
            "Target Date: 2026-05-01",
            "ID: 23",
            "Title: Month 1: MVP foundation",
            "Description: Build the first usable version",
            "Success Criteria: Working auth, Usable onboarding",
            "Title: Week 2: Validation",
            "Description: Test onboarding with users",
            "Week Number: 2",
            "Available Daily Time: 75 min",
            "Strengths: Fast iteration",
            "Blockers: Day job",
            "Motivation Style: intrinsic",
        ):
            self.assertIn(expected, prompt)

    def test_load_raises_useful_file_not_found_error_for_required_prompt_assets(self):
        with self.assertRaises(FileNotFoundError) as exc:
            _load("shared/does_not_exist.txt")

        self.assertIn("Required prompt file not found:", str(exc.exception))
        self.assertIn("does_not_exist.txt", str(exc.exception))


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
        job = AIProcessingJob.objects.create(
            user=self.user,
            job_type="situation_analysis",
        )
        mock_generate.return_value = {"data": None, "job_id": str(job.id)}

        response = self.client.post(
            reverse("ai-process-text-data-current-situation"),
            data={"raw_data": "I am currently stuck and need help."},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "Invalid AI response payload")

    @patch("ai.views.CurrentSituationGenerator.generate")
    def test_process_current_situation_returns_provider_failure_contract(self, mock_generate):
        mock_generate.side_effect = CurrentSituationGenerationError(
            "provider unavailable",
            code="ai_provider_unavailable",
            http_status=503,
            job_id="job-123",
        )

        response = self.client.post(
            reverse("ai-process-text-data-current-situation"),
            data={"raw_data": "I am currently stuck and need help."},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data["status"], "error")
        self.assertEqual(response.data["code"], "ai_provider_unavailable")
        self.assertEqual(response.data["job_id"], "job-123")

    @patch("ai.views.CurrentSituationGenerator.generate")
    def test_process_current_situation_refreshes_existing_record(self, mock_generate):
        job = AIProcessingJob.objects.create(
            user=self.user,
            job_type="situation_analysis",
        )
        mock_generate.side_effect = [
            {
                "data": {
                    "current_role": "Designer",
                    "age": 29,
                    "key_skills": ["Figma"],
                    "main_goals": ["Build portfolio"],
                    "time_availability": "5 hours",
                    "constraints": ["budget"],
                    "priority_areas": ["career"],
                },
                "job_id": str(job.id),
            },
            {
                "data": {
                    "current_role": "Product Designer",
                    "age": 29,
                    "key_skills": ["Figma", "Research"],
                    "main_goals": ["Get promoted"],
                    "time_availability": "8 hours",
                    "constraints": ["time"],
                    "priority_areas": ["career", "learning"],
                },
                "job_id": str(job.id),
            },
        ]

        url = reverse("ai-process-text-data-current-situation")
        first = self.client.post(url, data={"raw_data": "first"}, format="json")
        second = self.client.post(url, data={"raw_data": "second"}, format="json")

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(AIProcessingJob.objects.filter(user=self.user, job_type="situation_analysis").count(), 1)

        record = job.current_situation_goal
        self.assertEqual(record.current_role, "Product Designer")
        self.assertEqual(record.key_skills, ["Figma", "Research"])
        self.assertEqual(record.main_goals, ["Get promoted"])
        self.assertEqual(record.time_availability, "8 hours")
        self.assertEqual(record.constraints, ["time"])
        self.assertEqual(record.priority_areas, ["career", "learning"])

    @patch("ai.views.GoalAttributeExtractor.extract_goal_attributes")
    def test_goal_attribute_extractor_persists_goal_attributes_and_declares_it(self, mock_extract):
        goal = Goal.objects.create(
            user=self.user,
            title="Save for house",
            primary_category="finance",
        )
        mock_extract.return_value = {
            "status": "success",
            "data": {
                "financial_data": {
                    "target_amount": 500000,
                    "current_amount": 75000,
                }
            },
            "job_id": "job-goal-attr",
        }

        response = self.client.post(
            reverse("goal-attribute-extractor"),
            data={"user_input": "Save 500000 for house deposit", "goal_id": str(goal.id)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["persisted"])
        goal.refresh_from_db()
        self.assertEqual(
            goal.attributes.financial_data,
            {"target_amount": 500000, "current_amount": 75000},
        )

    @patch("ai.services.current_situation_generator.ResponseFormatter")
    @patch("ai.services.current_situation_generator.ResponseParser")
    @patch("ai.services.current_situation_generator.SystemPrompts")
    @patch("ai.services.current_situation_generator.UserContextPrompt")
    @patch("ai.services.current_situation_generator.create_routed_provider")
    @patch("ai.services.current_situation_generator.get_model_for_task", return_value="test-situation-model")
    def test_current_situation_generator_uses_job_helpers_for_lifecycle_fields(
        self,
        _mock_model,
        mock_provider_factory,
        mock_user_prompt_cls,
        mock_system_prompts_cls,
        mock_parser_cls,
        mock_formatter_cls,
    ):
        provider = mock_provider_factory.return_value
        provider.model = "test-situation-model"
        provider.generate_response.return_value = AIResponse(
            content='{"current_role": "Designer", "age": 29}',
            model="test-situation-model",
            token_used=321,
        )
        mock_user_prompt_cls.return_value.format.return_value = "formatted prompt"
        mock_system_prompts_cls.return_value.get_current_situation_prompt.return_value = "system prompt"
        mock_parser_cls.return_value.parse_current_situation_response.return_value = {
            "current_role": "Designer",
            "age": 29,
        }
        mock_formatter_cls.return_value.format_success.side_effect = (
            lambda **kwargs: {"data": kwargs["parsed_data"], "job_id": str(kwargs["job"].id)}
        )

        service = CurrentSituationGenerator()
        result = service.generate("I am a designer", 29, self.user)

        job = AIProcessingJob.objects.get(id=result["job_id"])
        self.assertEqual(job.status, "completed")
        self.assertEqual(job.progress_percentage, 100)
        self.assertEqual(job.ai_model_used, "test-situation-model")
        self.assertEqual(job.ai_tokens_used, 321)
        self.assertEqual(job.user_raw_text, "I am a designer")
        self.assertIsNotNone(job.started_at)
        self.assertIsNotNone(job.completed_at)
        self.assertGreaterEqual(job.processing_time_seconds, 0)

    def test_mark_completed_updates_daily_usage_stats(self):
        job = AIProcessingJob.objects.create(
            user=self.user,
            job_type="goal_attributes",
            ai_model_used="test-model",
        )

        job.start_processing()
        job.mark_completed(
            output_data={"ok": True},
            raw_response="{}",
            model_used="test-model",
            tokens=144,
            cost=Decimal("0.2500"),
        )

        stats = AIModelUsageStats.objects.get(user=self.user)
        self.assertEqual(stats.total_jobs, 1)
        self.assertEqual(stats.successful_jobs, 1)
        self.assertEqual(stats.failed_jobs, 0)
        self.assertEqual(stats.total_tokens, 144)
        self.assertEqual(str(stats.total_cost_usd), "0.2500")
        self.assertEqual(stats.model_usage["test-model"]["tokens"], 144)
        self.assertEqual(stats.job_type_usage["goal_attributes"]["count"], 1)

    @patch("ai.views.get_default_router")
    def test_health_check_handles_provider_os_error(self, mock_get_router):
        mock_get_router.return_value.health_check.side_effect = OSError("provider unavailable")
        response = self.client.get(reverse("ai-health-check"))

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data["status"], "unhealthy")
        self.assertEqual(response.data["service"], "router")


class OllamaProviderEnvConfigTests(TestCase):
    @patch("ai.providers.ollama_provider.Client")
    def test_provider_uses_default_host_when_env_is_not_passed(self, mock_client):
        with patch.dict(os.environ, {"OLLAMA_HOST": "", "OLLAMA_MODEL": "demo-model"}, clear=False):
            provider = OllamaProvider()

        mock_client.assert_called_once()
        called_kwargs = mock_client.call_args.kwargs
        self.assertEqual(called_kwargs["host"], "http://localhost:11434")
        self.assertEqual(provider.host, "http://localhost:11434")

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

    @patch("ai.views.get_default_router")
    def test_health_check_uses_default_host_when_env_is_missing(self, mock_get_router):
        mock_get_router.return_value.health_check.return_value = {
            "status": "healthy",
            "service": "ollama",
            "host": "http://localhost:11434",
            "model": "gpt-oss:120b-cloud",
            "error": None,
        }
        with patch.dict(os.environ, {"OLLAMA_HOST": "", "OLLAMA_MODEL": ""}, clear=False):
            response = self.client.get(reverse("ai-health-check"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "healthy")
        self.assertEqual(response.data["service"], "ollama")
        self.assertEqual(response.data["host"], "http://localhost:11434")
        self.assertEqual(response.data["model"], "gpt-oss:120b-cloud")

    @patch("ai.views.get_default_router")
    def test_health_check_uses_default_model_when_ollama_model_is_missing(self, mock_get_router):
        mock_get_router.return_value.health_check.return_value = {
            "status": "healthy",
            "service": "ollama",
            "host": "http://localhost:11434",
            "model": "gpt-oss:120b-cloud",
            "error": None,
        }
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


class DeadModuleCleanupTests(TestCase):
    def test_dead_goal_generator_module_is_removed(self):
        dead_module = Path(__file__).resolve().parent / "services" / "goal_generator.py"
        self.assertFalse(dead_module.exists())


class HierarchyPartialFailureTests(TestCase):
    @patch("ai.services.GoalHierarchyGenerator.create_routed_provider")
    @patch("ai.services.GoalHierarchyGenerator.get_hierarchy_model", return_value="test-hierarchy-model")
    def test_generate_complete_hierarchy_surfaces_partial_failures(self, _mock_model, mock_provider_factory):
        user = get_user_model().objects.create_user(
            email="hierarchy-partial@test.com",
            password="testpass123",
        )
        mock_provider_factory.return_value.model = "test-hierarchy-model"
        generator = GoalHierarchyGenerator()

        with patch.object(
            generator,
            "_generate_milestones",
            return_value={"status": "success", "data": {"milestones": [{"title": "Month 1"}]}},
        ), patch.object(
            generator,
            "_generate_subgoals",
            return_value={"status": "success", "data": {"subgoals": [{"title": "Week 1"}]}},
        ), patch.object(
            generator,
            "_generate_tasks",
            return_value={"status": "error", "message": "Task provider timeout", "data": {"tasks": []}},
        ):
            result = generator.generate_complete_hierarchy(
                goal_data={
                    "id": "goal-1",
                    "title": "Launch MVP",
                    "primary_category": "business",
                    "start_date": str(timezone.localdate()),
                    "target_date": str(timezone.localdate() + timedelta(days=30)),
                },
                user=user,
                user_context={},
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["partial_failure_count"], 1)
        self.assertEqual(result["data"]["partial_failures"][0]["stage"], "task_generation")
        subgoal_entry = result["data"]["milestones"][0]["subgoals"][0]
        self.assertEqual(subgoal_entry["generation_error"]["message"], "Task provider timeout")


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
