from datetime import timedelta
from unittest.mock import patch

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from authentication.models import CustomUser
from ai.models import AIProcessingJob
from goal.models import Goal, Milestone, SubGoal, Task, GoalLink, UserFinancialProfile, FinancialProgressEntry
from goal.services.goal_domain import build_goal_seed_data
from goal.services.financial_intelligence import build_financial_plan_summary


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

    def test_goal_create_endpoint_creates_goal(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            "/goal/",
            data={
                "title": "Service Refactor Goal",
                "description": "Created through endpoint",
                "why_it_matters": ["Consistency"],
                "primary_category": "career",
                "priority": "medium",
                "target_date": str(timezone.localdate() + timedelta(days=30)),
                "commitment_confirmed": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("goal", response.data)
        self.assertEqual(response.data["message"], "Goal created successfully!")
        self.assertTrue(
            Goal.objects.filter(id=response.data["goal"]["id"], user=self.owner).exists()
        )

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
            "target_date": str(timezone.localdate() + timedelta(days=90)),
            "commitment_confirmed": True,
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

    def test_goal_create_normalizes_why_it_matters_string_to_list(self):
        payload = {
            **self.base_payload,
            "why_it_matters": "Security\nFreedom\nSecurity",
        }
        response = self.client.post("/goal/", data=payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        goal = Goal.objects.get(id=response.data["goal"]["id"])
        self.assertEqual(goal.why_it_matters, ["Security", "Freedom"])

    def test_create_with_hierarchy_rejects_missing_required_fields_with_stable_contract(self):
        payload = {**self.base_payload}
        payload.pop("specific_measurable_target")
        response = self.client.post("/goal/create-with-hierarchy/", data=payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "validation_error")
        self.assertEqual(response.data["code"], "validation_error")
        self.assertIn("specific_measurable_target", response.data["details"])

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
            "primary_category": "career",
            "priority": "medium",
            "target_date": str(timezone.localdate() + timedelta(days=45)),
            "commitment_confirmed": True,
            "goal_attributes_input": "Learn machine learning fundamentals in 60 days",
        }

    def test_async_create_returns_failed_job_when_ai_runtime_not_configured(self):
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

    def test_sync_create_returns_created_goal_with_hierarchy_unavailable_message(self):
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
            "commitment_confirmed": True,
        }

    @patch("goal.views.get_missing_ai_env_vars", return_value=[])
    @patch("goal.views.threading.Thread")
    def test_async_worker_starts_only_after_transaction_commit(
        self,
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
            "primary_category": "financial",
            "priority": "medium",
            "target_date": str(timezone.localdate() + timedelta(days=300)),
            "commitment_confirmed": True,
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

    def test_create_infeasible_with_proceed_anyway_persists_metadata(self):
        response = self.client.post(
            "/goal/",
            data=self._financial_payload(financial_proceed_anyway=True),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        goal = Goal.objects.get(id=response.data["goal"]["id"])
        self.assertEqual(goal.financial_feasibility_status, "infeasible")
        self.assertIsNotNone(goal.financial_required_monthly_savings)
        self.assertIsNotNone(goal.financial_months_remaining)
        self.assertIsNotNone(goal.financial_gap_amount)

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
                    "primary_category": "financial",
                    "priority": "medium",
                    "target_date": str(timezone.localdate() + timedelta(days=300)),
                    "commitment_confirmed": True,
                    "financial_target_amount": "640000.00",
                    "financial_current_saved": "100000.00",
                    "financial_goal_type": "investment",
                    "financial_timeline_flexibility": "fixed",
                    "financial_proceed_anyway": True,
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("financial_plan_summary", response.data)
        self.assertIn("income_growth_path", response.data["financial_plan_summary"])


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
                    "primary_category": "financial",
                    "priority": "medium",
                    "target_date": feasibility_payload["target_date"],
                    "commitment_confirmed": True,
                    "financial_target_amount": feasibility_payload["target_amount"],
                    "financial_current_saved": feasibility_payload["current_saved"],
                    "financial_goal_type": "investment",
                    "financial_timeline_flexibility": feasibility_payload["timeline_flexibility"],
                },
                format="json",
            )

        self.assertEqual(create_goal.status_code, status.HTTP_201_CREATED)
        self.assertIn("goal", create_goal.data)
        self.assertIn("financial_plan_summary", create_goal.data)
        self.assertEqual(
            create_goal.data["financial_plan_summary"]["feasibility_summary"]["feasibility_status"],
            "pass",
        )
        self.assertEqual(create_goal.data["needs_profile_review"], False)

        goal = Goal.objects.get(id=create_goal.data["goal"]["id"], user=self.user)
        self.assertEqual(goal.primary_category, "financial")
        self.assertEqual(goal.financial_feasibility_status, "pass")
        self.assertIsNotNone(goal.financial_required_monthly_savings)


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
            "title": title,
            "description": "E2E lifecycle verification",
            "why_it_matters": ["Consistency"],
            "primary_category": primary_category,
            "priority": "medium",
            "target_date": str(timezone.localdate() + timedelta(days=target_days)),
            "commitment_confirmed": True,
        }
        if primary_category == "financial":
            payload.update(
                {
                    "financial_target_amount": "500000.00",
                    "financial_current_saved": "100000.00",
                    "financial_goal_type": "investment",
                    "financial_timeline_flexibility": "fixed",
                }
            )

        response = self.client.post(
            "/goal/",
            data=payload,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.data["goal"]["id"]

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
        response = self.client.post(
            "/goal/",
            data={
                "title": "Financial Monthly Reconciliation Goal",
                "description": "Cross-cutting monthly reconciliation verification",
                "why_it_matters": ["Stability"],
                "primary_category": "financial",
                "priority": "medium",
                "target_date": str(timezone.localdate() + timedelta(days=180)),
                "commitment_confirmed": True,
                "financial_target_amount": "250000.00",
                "financial_current_saved": "100000.00",
                "financial_goal_type": "investment",
                "financial_timeline_flexibility": "fixed",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.data["goal"]["id"]

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
