from datetime import timedelta

from django.http import Http404
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from authentication.core.response import ApiResponse as AuthApiResponse
from authentication.core.response import created_response as auth_created_response
from authentication.core.response import error_response as auth_error_response
from authentication.core.response import success_response as auth_success_response
from authentication.models import CustomUser
from common.ownership import get_owned_object_or_404
from common.responses import ApiResponse as SharedApiResponse
from common.responses import created_response as shared_created_response
from common.responses import error_response as shared_error_response
from common.responses import success_response as shared_success_response
from goal.core.response import ApiResponse as GoalApiResponse
from goal.core.response import created_response as goal_created_response
from goal.core.response import error_response as goal_error_response
from goal.core.response import success_response as goal_success_response
from goal.models import Goal, Milestone, SubGoal, Task


class SharedResponseCompatibilityTests(APITestCase):
    def test_auth_and_goal_response_helpers_reexport_shared_helper(self):
        self.assertIs(auth_success_response, shared_success_response)
        self.assertIs(goal_success_response, shared_success_response)

    def test_auth_and_goal_core_modules_reexport_all_response_helpers(self):
        self.assertIs(AuthApiResponse, SharedApiResponse)
        self.assertIs(GoalApiResponse, SharedApiResponse)
        self.assertIs(auth_created_response, shared_created_response)
        self.assertIs(goal_created_response, shared_created_response)
        self.assertIs(auth_error_response, shared_error_response)
        self.assertIs(goal_error_response, shared_error_response)

    def test_reexported_helpers_keep_shared_response_contract(self):
        created_response = auth_created_response(
            data={"id": "123"},
            message="created",
        )
        error_response = goal_error_response(
            message="failed",
            errors={"field": ["invalid"]},
            code="validation_error",
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
        self.assertEqual(created_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(created_response.data["success"], True)
        self.assertEqual(created_response.data["message"], "created")
        self.assertEqual(created_response.data["data"]["id"], "123")
        self.assertEqual(error_response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertEqual(error_response.data["success"], False)
        self.assertEqual(error_response.data["message"], "failed")
        self.assertEqual(error_response.data["code"], "validation_error")
        self.assertEqual(error_response.data["errors"]["field"], ["invalid"])


class SharedOwnershipHelperTests(APITestCase):
    def setUp(self):
        self.owner = CustomUser.objects.create_user(
            email="owner-common@test.com",
            password="Password@123",
        )
        self.other_user = CustomUser.objects.create_user(
            email="other-common@test.com",
            password="Password@123",
        )
        goal = Goal.objects.create(
            user=self.owner,
            title="Common Layer Goal",
            primary_category="career",
            target_date=timezone.localdate() + timedelta(days=30),
        )
        milestone = Milestone.objects.create(
            goal=goal,
            title="Common Layer Milestone",
            display_order=1,
            status="in_progress",
        )
        subgoal = SubGoal.objects.create(
            milestone=milestone,
            title="Common Layer Subgoal",
            display_order=1,
            status="in_progress",
        )
        self.task = Task.objects.create(
            subgoal=subgoal,
            title="Common Layer Task",
            status="pending",
            priority="medium",
            estimated_duration_minutes=45,
            display_order=1,
        )

    def test_get_owned_object_or_404_allows_owner(self):
        task = get_owned_object_or_404(
            Task,
            id=self.task.id,
            user=self.owner,
            owner_filter="subgoal__milestone__goal__user",
        )
        self.assertEqual(task.id, self.task.id)

    def test_get_owned_object_or_404_rejects_non_owner(self):
        with self.assertRaises(Http404):
            get_owned_object_or_404(
                Task,
                id=self.task.id,
                user=self.other_user,
                owner_filter="subgoal__milestone__goal__user",
            )
