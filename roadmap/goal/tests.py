from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from authentication.models import CustomUser
from ai.models import AIProcessingJob
from goal.models import Goal, Milestone, SubGoal, Task


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
