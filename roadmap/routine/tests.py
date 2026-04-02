from datetime import date, datetime, timedelta
from io import StringIO
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.utils import timezone
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from authentication.models import CustomUser, Profile
from ai.services.DailyRoutineGenerator import DailyRoutineGenerator
from events.models import Event
from gie.models import GIEPlanSnapshot, GIESession
from goal.models import Goal, Milestone, SubGoal, Task
from journal.models import JournalEntry
from routine.models import (
    AdaptiveRoadmapState,
    DailyTaskList,
    DailyTaskItem,
    DisciplineStreak,
    HabitTracker,
    HealthProfile,
    GoalProgressEntry,
    DailyBrief,
    RoutineDayModeCheckIn,
    WakeBaselineState,
    WakeInteraction,
    PointsWallet,
    PointsTransaction,
    RewardCatalogItem,
)
from routine.services import (
    _fetch_day_event_constraints,
    _get_event_occurrences_for_day,
    _load_rie_signal_for_goal,
    _resolve_and_persist_day_mode,
    _select_balanced_goal_tasks,
    build_adaptive_roadmap_adjustment,
    get_or_create_today_task_list,
)
from routine.system_habits_service import seed_system_habits_for_user
from routine.wake_service import sync_wake_baseline_for_user
from routine.habit_recommendation_service import (
    _build_habit_prompt,
    _normalize_ai_habit,
    generate_habit_recommendations_for_user,
)


class RoutineCompletionCascadeTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="cascade@test.com",
            password="Password@123",
        )
        self.client.force_authenticate(self.user)

    def test_complete_task_item_updates_goal_hierarchy_and_daily_progress(self):
        goal = Goal.objects.create(
            user=self.user,
            title="Master ML Basics",
            description="Build foundational ML skills",
            primary_category="career",
            priority="high",
            target_date=timezone.localdate() + timedelta(days=30),
        )
        milestone = Milestone.objects.create(
            goal=goal,
            title="Month 1 Foundation",
            description="Core fundamentals",
            display_order=1,
            priority="high",
        )
        subgoal = SubGoal.objects.create(
            milestone=milestone,
            title="Week 1 Fundamentals",
            description="Complete foundation tasks",
            display_order=1,
            priority="high",
        )
        goal_task = Task.objects.create(
            subgoal=subgoal,
            title="Study core concepts",
            description="Complete first module",
            status="pending",
            priority="high",
            estimated_duration_minutes=90,
            display_order=1,
        )

        task_list = DailyTaskList.objects.create(
            user=self.user,
            date=timezone.localdate(),
        )
        daily_item = DailyTaskItem.objects.create(
            task_list=task_list,
            item_type="goal_task",
            goal_task=goal_task,
            related_goal=goal,
            title=goal_task.title,
            description=goal_task.description,
            priority=goal_task.priority,
            estimated_minutes=goal_task.estimated_duration_minutes,
            display_order=0,
        )
        task_list.update_progress()

        response = self.client.post(f"/routines/tasks/{daily_item.id}/complete/", data={}, secure=True)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        daily_item.refresh_from_db()
        task_list.refresh_from_db()
        goal_task.refresh_from_db()
        subgoal.refresh_from_db()
        milestone.refresh_from_db()
        goal.refresh_from_db()

        self.assertTrue(daily_item.is_completed)
        self.assertEqual(task_list.completion_percentage, 100)
        self.assertEqual(goal_task.status, "completed")
        self.assertEqual(subgoal.status, "completed")
        self.assertEqual(milestone.status, "completed")
        self.assertEqual(goal.status, "completed")
        self.assertEqual(goal.progress_percentage, 100)
        self.assertEqual(Decimal(str(response.data["wallet"]["awarded_points"])), Decimal("15.0000"))
        wallet = PointsWallet.objects.get(user=self.user)
        self.assertEqual(wallet.current_balance, Decimal("15.0000"))
        self.assertEqual(wallet.lifetime_earned, Decimal("15.0000"))
        ledger_entry = PointsTransaction.objects.get(task_item=daily_item)
        self.assertEqual(ledger_entry.source_type, PointsTransaction.SOURCE_TASK_COMPLETION)
        self.assertEqual(ledger_entry.amount, Decimal("15.0000"))

    def test_event_task_item_supports_complete_and_skip_without_goal_habit_cascade(self):
        target_date = timezone.localdate()
        event = Event.objects.create(
            user=self.user,
            title="Client Call",
            description="Planned sync",
            event_type="one_time",
            start_at=datetime.fromisoformat(f"{target_date.isoformat()}T10:00:00+00:00"),
            end_at=datetime.fromisoformat(f"{target_date.isoformat()}T11:00:00+00:00"),
            is_all_day=False,
            timezone="UTC",
            recurrence=None,
            routine_constraint={"constraint_mode": "hard", "routine_policy": "block"},
        )

        task_list = DailyTaskList.objects.create(user=self.user, date=target_date)
        complete_item = DailyTaskItem.objects.create(
            task_list=task_list,
            item_type="event",
            event=event,
            title=event.title,
            description=event.description,
            priority="high",
            estimated_minutes=60,
            display_order=0,
        )
        skip_item = DailyTaskItem.objects.create(
            task_list=task_list,
            item_type="event",
            event=event,
            title="Client Call Follow-up",
            description="Prep and context notes",
            priority="medium",
            estimated_minutes=30,
            display_order=1,
        )
        task_list.update_progress()

        complete_response = self.client.post(
            f"/routines/tasks/{complete_item.id}/complete/",
            data={},
            secure=True,
        )
        self.assertEqual(complete_response.status_code, status.HTTP_200_OK)
        complete_item.refresh_from_db()
        self.assertTrue(complete_item.is_completed)

        skip_response = self.client.post(
            f"/routines/tasks/{skip_item.id}/skip/",
            data={"reason": "Rescheduled"},
            secure=True,
        )
        self.assertEqual(skip_response.status_code, status.HTTP_200_OK)
        skip_item.refresh_from_db()
        self.assertTrue(skip_item.is_skipped)

        task_list.refresh_from_db()
        self.assertEqual(task_list.total_tasks, 2)
        self.assertEqual(task_list.completed_tasks, 1)

    def test_complete_task_item_uses_base_points_scaling_for_wallet_credit(self):
        task_list = DailyTaskList.objects.create(user=self.user, date=timezone.localdate())
        prior_completed_items = [
            DailyTaskItem(
                task_list=task_list,
                item_type="manual_task",
                title=f"Done {index}",
                priority="low",
                estimated_minutes=10,
                display_order=index,
                is_completed=True,
                completed_at=timezone.now(),
            )
            for index in range(90)
        ]
        DailyTaskItem.objects.bulk_create(prior_completed_items)
        task_item = DailyTaskItem.objects.create(
            task_list=task_list,
            item_type="manual_task",
            title="Scaled task",
            priority="high",
            estimated_minutes=30,
            display_order=100,
            base_points=Decimal("12.5000"),
        )

        response = self.client.post(
            f"/routines/tasks/{task_item.id}/complete/",
            data={},
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        wallet = PointsWallet.objects.get(user=self.user)
        transaction_entry = PointsTransaction.objects.get(task_item=task_item)
        self.assertEqual(transaction_entry.amount, Decimal("6.2500"))
        self.assertEqual(wallet.current_balance, Decimal("6.2500"))
        self.assertEqual(wallet.lifetime_earned, Decimal("6.2500"))
        self.assertEqual(Decimal(str(response.data["wallet"]["awarded_points"])), Decimal("6.2500"))


class RoutineWriteValidationTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="routine-validation@test.com",
            password="Password@123",
        )
        self.client.force_authenticate(self.user)

        goal = Goal.objects.create(
            user=self.user,
            title="Validation Goal",
            description="Validation coverage test",
            primary_category="career",
            status="in_progress",
            target_date=timezone.localdate() + timedelta(days=20),
        )
        milestone = Milestone.objects.create(
            goal=goal,
            title="Validation Milestone",
            display_order=1,
            status="in_progress",
        )
        subgoal = SubGoal.objects.create(
            milestone=milestone,
            title="Validation Subgoal",
            display_order=1,
            status="in_progress",
        )
        goal_task = Task.objects.create(
            subgoal=subgoal,
            title="Validation Task",
            status="pending",
            priority="medium",
            estimated_duration_minutes=45,
            display_order=1,
        )
        task_list = DailyTaskList.objects.create(
            user=self.user,
            date=timezone.localdate(),
        )
        self.daily_item = DailyTaskItem.objects.create(
            task_list=task_list,
            item_type="goal_task",
            goal_task=goal_task,
            related_goal=goal,
            title=goal_task.title,
            description=goal_task.description,
            priority=goal_task.priority,
            estimated_minutes=goal_task.estimated_duration_minutes,
            display_order=0,
        )

    def test_generate_endpoint_rejects_invalid_date_via_serializer(self):
        response = self.client.post("/routines/generate/", data={"date": "2026/01/31"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "Invalid date format. Use YYYY-MM-DD.")

    def test_generate_endpoint_rejects_invalid_day_mode(self):
        response = self.client.post(
            "/routines/generate/",
            data={"day_mode": "unplanned"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "\"unplanned\" is not a valid choice.")

    def test_complete_endpoint_rejects_invalid_actual_minutes(self):
        response = self.client.post(
            f"/routines/tasks/{self.daily_item.id}/complete/",
            data={"actual_minutes": "not-a-number"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("actual_minutes", response.data)

    def test_skip_endpoint_rejects_invalid_reason_type(self):
        response = self.client.post(
            f"/routines/tasks/{self.daily_item.id}/skip/",
            data={"reason": {"unexpected": "object"}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("reason", response.data)


class RoutineTaskReorderAPITests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="routine-reorder@test.com",
            password="Password@123",
        )
        self.other_user = CustomUser.objects.create_user(
            email="routine-reorder-other@test.com",
            password="Password@123",
        )
        self.client.force_authenticate(self.user)

        self.task_list = DailyTaskList.objects.create(
            user=self.user,
            date=timezone.localdate(),
        )
        self.task_a = DailyTaskItem.objects.create(
            task_list=self.task_list,
            item_type="goal_task",
            title="Task A",
            priority="high",
            estimated_minutes=30,
            display_order=0,
        )
        self.task_b = DailyTaskItem.objects.create(
            task_list=self.task_list,
            item_type="goal_task",
            title="Task B",
            priority="medium",
            estimated_minutes=20,
            display_order=1,
        )
        self.task_c = DailyTaskItem.objects.create(
            task_list=self.task_list,
            item_type="goal_task",
            title="Task C",
            priority="low",
            estimated_minutes=15,
            display_order=2,
        )
        self.reorder_url = f"/routines/{self.task_list.id}/reorder/"

    def test_reorder_endpoint_persists_and_returns_ordered_tasks(self):
        ordered_ids = [self.task_c.id, self.task_a.id, self.task_b.id]
        response = self.client.patch(
            self.reorder_url,
            data={"task_ids": ordered_ids},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [item["id"] for item in response.data["tasks"]],
            [str(task_id) for task_id in ordered_ids],
        )

        db_order = list(
            DailyTaskItem.objects.filter(task_list=self.task_list)
            .order_by("display_order")
            .values_list("id", flat=True)
        )
        self.assertEqual(db_order, ordered_ids)

    def test_reorder_endpoint_rejects_invalid_membership_or_duplicates(self):
        missing_one_response = self.client.patch(
            self.reorder_url,
            data={"task_ids": [self.task_a.id, self.task_b.id]},
            format="json",
        )
        self.assertEqual(missing_one_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("task_ids must include each routine task id exactly once", missing_one_response.data["error"])

        duplicate_response = self.client.patch(
            self.reorder_url,
            data={"task_ids": [self.task_a.id, self.task_b.id, self.task_b.id]},
            format="json",
        )
        self.assertEqual(duplicate_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("duplicate", duplicate_response.data["error"])

    def test_reorder_endpoint_forbids_non_owner(self):
        self.client.force_authenticate(self.other_user)
        response = self.client.patch(
            self.reorder_url,
            data={"task_ids": [self.task_a.id, self.task_b.id, self.task_c.id]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class RoutineTaskSoftRemoveAPITests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="routine-remove@test.com",
            password="Password@123",
        )
        self.other_user = CustomUser.objects.create_user(
            email="routine-remove-other@test.com",
            password="Password@123",
        )
        self.client.force_authenticate(self.user)
        self.task_list = DailyTaskList.objects.create(user=self.user, date=timezone.localdate())
        self.habit = HabitTracker.objects.create(
            user=self.user,
            name="Hydration",
            frequency="daily",
            estimated_minutes=5,
            priority="low",
        )
        self.generated_task = DailyTaskItem.objects.create(
            task_list=self.task_list,
            item_type="habit",
            habit=self.habit,
            title="Drink water",
            priority="low",
            estimated_minutes=5,
            display_order=0,
        )
        self.manual_task = DailyTaskItem.objects.create(
            task_list=self.task_list,
            item_type="manual_task",
            title="Manual routine note",
            priority="medium",
            estimated_minutes=20,
            display_order=1,
        )
        self.task_list.update_progress()

    def test_remove_generated_task_success_and_today_list_excludes_removed(self):
        remove_response = self.client.post(
            f"/routines/tasks/{self.generated_task.id}/remove/",
            data={},
            format="json",
        )
        self.assertEqual(remove_response.status_code, status.HTTP_200_OK)
        self.generated_task.refresh_from_db()
        self.assertTrue(self.generated_task.removed_by_user)
        self.assertIsNotNone(self.generated_task.removed_at)

        today_response = self.client.get("/routines/today/?detailed=true")
        self.assertEqual(today_response.status_code, status.HTTP_200_OK)
        returned_ids = [task["id"] for task in today_response.data["task_list"]["tasks"]]
        self.assertNotIn(str(self.generated_task.id), returned_ids)
        self.assertIn(str(self.manual_task.id), returned_ids)

    def test_restore_removed_generated_task_success(self):
        self.client.post(f"/routines/tasks/{self.generated_task.id}/remove/", data={}, format="json")
        restore_response = self.client.post(
            f"/routines/tasks/{self.generated_task.id}/restore/",
            data={},
            format="json",
        )
        self.assertEqual(restore_response.status_code, status.HTTP_200_OK)
        self.generated_task.refresh_from_db()
        self.assertFalse(self.generated_task.removed_by_user)
        self.assertIsNone(self.generated_task.removed_at)

    def test_remove_and_restore_forbid_non_owner(self):
        self.client.force_authenticate(self.other_user)
        remove_response = self.client.post(
            f"/routines/tasks/{self.generated_task.id}/remove/",
            data={},
            format="json",
        )
        restore_response = self.client.post(
            f"/routines/tasks/{self.generated_task.id}/restore/",
            data={},
            format="json",
        )
        self.assertEqual(remove_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(restore_response.status_code, status.HTTP_404_NOT_FOUND)

    def test_remove_manual_task_rejected(self):
        remove_response = self.client.post(
            f"/routines/tasks/{self.manual_task.id}/remove/",
            data={},
            format="json",
        )
        self.assertEqual(remove_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Only generated routine tasks", remove_response.data["error"])

    def test_reorder_only_requires_active_task_ids(self):
        self.client.post(f"/routines/tasks/{self.generated_task.id}/remove/", data={}, format="json")
        reorder_response = self.client.patch(
            f"/routines/{self.task_list.id}/reorder/",
            data={"task_ids": [self.manual_task.id]},
            format="json",
        )
        self.assertEqual(reorder_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(reorder_response.data["tasks"]), 1)
        self.assertEqual(reorder_response.data["tasks"][0]["id"], str(self.manual_task.id))


class RoutineTaskInlineManagementAPITests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="routine-inline@test.com",
            password="Password@123",
        )
        self.other_user = CustomUser.objects.create_user(
            email="routine-inline-other@test.com",
            password="Password@123",
        )
        self.client.force_authenticate(self.user)
        self.task_list = DailyTaskList.objects.create(user=self.user, date=timezone.localdate())
        self.task_item = DailyTaskItem.objects.create(
            task_list=self.task_list,
            item_type="manual_task",
            title="Existing Task",
            priority="medium",
            estimated_minutes=25,
            display_order=0,
        )

    def test_create_task_under_routine(self):
        response = self.client.post(
            f"/routines/{self.task_list.id}/tasks/",
            data={
                "title": "New Routine Task",
                "description": "Created from routine page",
                "priority": "high",
                "estimated_minutes": 40,
                "base_points": "7.2500",
            },
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["task"]["title"], "New Routine Task")
        self.assertEqual(response.data["task"]["item_type"], "manual_task")
        self.assertEqual(response.data["task"]["display_order"], 1)
        self.assertEqual(response.data["task"]["base_points"], "7.2500")

    def test_create_task_rejects_blocked_schedule_slot(self):
        self.task_list.schedule_constraints = {
            "timezone": "UTC",
            "occupied_windows": [
                {
                    "start_at": f"{self.task_list.date.isoformat()}T06:00:00+00:00",
                    "end_at": f"{self.task_list.date.isoformat()}T12:00:00+00:00",
                    "constraint_mode": "hard",
                    "routine_policy": "block",
                }
            ],
        }
        self.task_list.save(update_fields=["schedule_constraints", "updated_at"])

        response = self.client.post(
            f"/routines/{self.task_list.id}/tasks/",
            data={
                "title": "Blocked Task",
                "estimated_minutes": 30,
                "time_slot": "morning",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "routine_task_conflicts_schedule")

    def test_patch_task_rejects_blocked_schedule_slot(self):
        self.task_list.schedule_constraints = {
            "timezone": "UTC",
            "occupied_windows": [
                {
                    "start_at": f"{self.task_list.date.isoformat()}T12:00:00+00:00",
                    "end_at": f"{self.task_list.date.isoformat()}T18:00:00+00:00",
                    "constraint_mode": "hard",
                    "routine_policy": "block",
                }
            ],
        }
        self.task_list.save(update_fields=["schedule_constraints", "updated_at"])

        response = self.client.patch(
            f"/routines/tasks/{self.task_item.id}/",
            data={"time_slot": "afternoon", "estimated_minutes": 30},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "routine_task_conflicts_schedule")

    def test_create_flexible_task_without_slot_still_succeeds(self):
        self.task_list.schedule_constraints = {
            "timezone": "UTC",
            "occupied_windows": [
                {
                    "start_at": f"{self.task_list.date.isoformat()}T06:00:00+00:00",
                    "end_at": f"{self.task_list.date.isoformat()}T23:59:59+00:00",
                    "constraint_mode": "hard",
                    "routine_policy": "block",
                }
            ],
        }
        self.task_list.save(update_fields=["schedule_constraints", "updated_at"])

        response = self.client.post(
            f"/routines/{self.task_list.id}/tasks/",
            data={"title": "Flexible Task", "estimated_minutes": 15},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["task"]["item_type"], "manual_task")

    def test_patch_task_detail_updates_fields(self):
        response = self.client.patch(
            f"/routines/tasks/{self.task_item.id}/",
            data={"title": "Updated Task Title", "estimated_minutes": 60, "base_points": "9.5000"},
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.task_item.refresh_from_db()
        self.assertEqual(self.task_item.title, "Updated Task Title")
        self.assertEqual(self.task_item.estimated_minutes, 60)
        self.assertEqual(self.task_item.base_points, Decimal("9.5000"))

    def test_delete_task_detail_removes_task(self):
        response = self.client.delete(f"/routines/tasks/{self.task_item.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(DailyTaskItem.objects.filter(id=self.task_item.id).exists())

    def test_inline_task_endpoints_forbid_non_owner(self):
        self.client.force_authenticate(self.other_user)
        patch_response = self.client.patch(
            f"/routines/tasks/{self.task_item.id}/",
            data={"title": "Nope"},
            format="json",
        )
        self.assertEqual(patch_response.status_code, status.HTTP_403_FORBIDDEN)

        delete_response = self.client.delete(f"/routines/tasks/{self.task_item.id}/")
        self.assertEqual(delete_response.status_code, status.HTTP_403_FORBIDDEN)


class PointsWalletRewardAPITests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="wallet@test.com",
            password="Password@123",
        )
        self.client.force_authenticate(self.user)
        self.task_list = DailyTaskList.objects.create(user=self.user, date=timezone.localdate())
        self.task_item = DailyTaskItem.objects.create(
            task_list=self.task_list,
            item_type="manual_task",
            title="Earn points",
            priority="medium",
            estimated_minutes=20,
            display_order=0,
            base_points=Decimal("30.0000"),
        )

    def test_wallet_endpoint_returns_zero_state_before_first_credit(self):
        response = self.client.get("/routines/wallet/", secure=True)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["wallet"]["current_balance"], "0.0000")
        self.assertFalse(response.data["wallet"]["has_wallet"])

    def test_wallet_transaction_endpoint_lists_task_credit(self):
        self.client.post(
            f"/routines/tasks/{self.task_item.id}/complete/",
            data={},
            format="json",
            secure=True,
        )

        response = self.client.get("/routines/wallet/transactions/", secure=True)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["source_type"], "task_completion")
        self.assertEqual(response.data["results"][0]["amount"], "30.0000")

    def test_reward_catalog_lists_seeded_rewards(self):
        response = self.client.get("/routines/rewards/", secure=True)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data["rewards"]), 3)

    def test_reward_redeem_debits_wallet_and_records_transaction(self):
        self.client.post(
            f"/routines/tasks/{self.task_item.id}/complete/",
            data={},
            format="json",
            secure=True,
        )
        reward = RewardCatalogItem.objects.order_by("cost").first()

        response = self.client.post(
            f"/routines/rewards/{reward.id}/redeem/",
            data={"note": "demo"},
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        wallet = PointsWallet.objects.get(user=self.user)
        self.assertEqual(wallet.current_balance, Decimal("5.0000"))
        self.assertEqual(wallet.lifetime_earned, Decimal("30.0000"))
        self.assertEqual(response.data["transaction"]["source_type"], "redemption")
        self.assertIn("demo", response.data["transaction"]["note"])

    def test_reward_redeem_rejects_when_balance_is_insufficient(self):
        reward = RewardCatalogItem.objects.order_by("-cost").first()
        response = self.client.post(
            f"/routines/rewards/{reward.id}/redeem/",
            data={},
            format="json",
            secure=True,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["detail"], "Insufficient points for this reward.")


class DailyTaskGenerationTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="schedule@test.com",
            password="Password@123",
        )

    def _create_goal_with_subgoal(
        self,
        title: str,
        priority: str = "medium",
        status: str = "in_progress",
        *,
        target_date: date | None = None,
        milestone_status: str = "in_progress",
    ):
        today = timezone.localdate()
        goal = Goal.objects.create(
            user=self.user,
            title=title,
            description=f"{title} description",
            primary_category="career",
            priority=priority,
            target_date=target_date or (today + timedelta(days=60)),
            status=status,
        )
        milestone = Milestone.objects.create(
            goal=goal,
            title=f"{title} Milestone",
            display_order=1,
            priority=priority,
            status=milestone_status,
        )
        subgoal = SubGoal.objects.create(
            milestone=milestone,
            title=f"{title} Subgoal",
            display_order=1,
            priority=priority,
            status="in_progress",
        )
        return goal, subgoal

    def test_generation_uses_target_date_for_habits_and_applies_time_slot_logic(self):
        today = timezone.localdate()
        target_date = today + timedelta(days=1)

        goal = Goal.objects.create(
            user=self.user,
            title="Trading Skill Growth",
            description="Practice daily with quality review",
            primary_category="financial",
            priority="high",
            target_date=today + timedelta(days=60),
            status="in_progress",
        )
        milestone = Milestone.objects.create(
            goal=goal,
            title="Month 1",
            display_order=1,
            priority="high",
            status="in_progress",
        )
        subgoal = SubGoal.objects.create(
            milestone=milestone,
            title="Week 1",
            display_order=1,
            priority="high",
            status="in_progress",
        )

        task_preferred_evening = Task.objects.create(
            subgoal=subgoal,
            title="Backtest setup",
            status="pending",
            priority="high",
            preferred_time_slot="evening",
            estimated_duration_minutes=80,
            display_order=1,
        )
        task_inferred_evening = Task.objects.create(
            subgoal=subgoal,
            title="Write evening journal reflection",
            status="pending",
            priority="medium",
            estimated_duration_minutes=30,
            display_order=2,
        )
        task_fallback_afternoon = Task.objects.create(
            subgoal=subgoal,
            title="Analyze chart pattern",
            status="pending",
            priority="medium",
            estimated_duration_minutes=60,
            display_order=3,
        )
        Task.objects.create(
            subgoal=subgoal,
            title="Already done task",
            status="completed",
            priority="low",
            estimated_duration_minutes=15,
            display_order=4,
        )

        # Must follow target_date weekday (not "today" weekday).
        HabitTracker.objects.create(
            user=self.user,
            name="Target day reading",
            frequency="custom",
            custom_days=[target_date.weekday()],
            is_active=True,
            estimated_minutes=20,
            priority="medium",
        )

        task_list, created = get_or_create_today_task_list(self.user, target_date)
        self.assertTrue(created)

        items = list(task_list.tasks.order_by("display_order"))
        self.assertGreaterEqual(len(items), 4)

        habit_items = [i for i in items if i.item_type == "habit"]
        goal_items = [i for i in items if i.item_type == "goal_task"]
        self.assertTrue(any(item.title == "Target day reading" for item in habit_items))
        self.assertEqual(len(goal_items), 3)

        by_task_id = {str(i.goal_task_id): i for i in goal_items if i.goal_task_id}
        self.assertEqual(by_task_id[str(task_preferred_evening.id)].time_slot, "evening")
        self.assertEqual(by_task_id[str(task_inferred_evening.id)].time_slot, "evening")
        self.assertEqual(by_task_id[str(task_fallback_afternoon.id)].time_slot, "afternoon")

    def test_generation_always_includes_system_habits_and_prefers_explicit_habit_time_slot(self):
        target_date = timezone.localdate() + timedelta(days=1)

        HabitTracker.objects.create(
            user=self.user,
            name="System Evening Habit",
            frequency="custom",
            custom_days=[(target_date.weekday() + 1) % 7],
            is_active=True,
            is_system=True,
            is_deletable=False,
            estimated_minutes=15,
            suggested_time=datetime.strptime("05:30:00", "%H:%M:%S").time(),
            time_slot="evening",
            priority="high",
        )

        task_list, created = get_or_create_today_task_list(self.user, target_date)
        self.assertTrue(created)

        habit_item = task_list.tasks.filter(item_type="habit", title="System Evening Habit").first()
        self.assertIsNotNone(habit_item)
        self.assertEqual(habit_item.time_slot, "evening")
        self.assertEqual(str(habit_item.suggested_time), "05:30:00")

    def test_generation_backfills_system_habit_guidance_and_uses_it_for_routine_description(self):
        target_date = timezone.localdate() + timedelta(days=1)
        expected_description = (
            "1. Close your eyes and slow your breathing.\n"
            "2. Picture your future self living the result you want.\n"
            "3. Add details: where you are, what you see, and how you feel.\n"
            "4. Connect that future to one action you must execute today."
        )

        HabitTracker.objects.filter(
            user=self.user,
            name="Visualization",
            is_system=True,
        ).update(description="", reason_body="")

        task_list, created = get_or_create_today_task_list(self.user, target_date)
        self.assertTrue(created)

        visualization_habit = HabitTracker.objects.get(
            user=self.user,
            name="Visualization",
            is_system=True,
        )
        self.assertEqual(visualization_habit.description, expected_description)
        self.assertEqual(visualization_habit.reason_body, expected_description)

        routine_item = task_list.tasks.filter(item_type="habit", title="Visualization").first()
        self.assertIsNotNone(routine_item)
        self.assertEqual(routine_item.description, expected_description)

    def test_generation_places_journal_before_sleep_preparation(self):
        target_date = timezone.localdate()
        goal, subgoal = self._create_goal_with_subgoal("Journal Rule Goal", priority="medium")
        Task.objects.create(
            subgoal=subgoal,
            title="Core task",
            status="pending",
            priority="medium",
            estimated_duration_minutes=45,
            display_order=1,
        )
        HabitTracker.objects.create(
            user=self.user,
            name="Sleep Preparation",
            description="Wind down and prepare for sleep.",
            frequency="daily",
            is_active=True,
            estimated_minutes=30,
            suggested_time=datetime.strptime("22:00:00", "%H:%M:%S").time(),
            time_slot="evening",
            priority="high",
        )

        task_list, created = get_or_create_today_task_list(self.user, target_date)
        self.assertTrue(created)
        ordered_titles = list(task_list.tasks.order_by("display_order").values_list("title", flat=True))
        self.assertGreaterEqual(len(ordered_titles), 2)
        self.assertEqual(ordered_titles[-2], "Evening journal entry")
        self.assertEqual(ordered_titles[-1], "Sleep Preparation")

    def test_generation_orders_same_time_morning_tasks_by_phase(self):
        target_date = timezone.localdate()
        goal, subgoal = self._create_goal_with_subgoal("Morning Ordering Goal", priority="high")
        Task.objects.create(
            subgoal=subgoal,
            title="Deep Work Session",
            status="pending",
            priority="high",
            preferred_time_slot="morning",
            scheduled_time=datetime.strptime("08:00:00", "%H:%M:%S").time(),
            estimated_duration_minutes=90,
            display_order=1,
        )
        HabitTracker.objects.create(
            user=self.user,
            name="Review Today's Plan",
            frequency="daily",
            is_active=True,
            estimated_minutes=10,
            suggested_time=datetime.strptime("08:00:00", "%H:%M:%S").time(),
            time_slot="morning",
            priority="medium",
        )

        task_list, created = get_or_create_today_task_list(self.user, target_date)
        self.assertTrue(created)
        morning_titles = list(
            task_list.tasks.filter(time_slot="morning").order_by("display_order").values_list("title", flat=True)
        )
        self.assertLess(morning_titles.index("Review Today's Plan"), morning_titles.index("Deep Work Session"))

    def test_generation_orders_prep_goal_tasks_before_analysis_tasks_at_same_time(self):
        target_date = timezone.localdate()
        goal, subgoal = self._create_goal_with_subgoal("Trade Review Goal", priority="high")
        Task.objects.create(
            subgoal=subgoal,
            title="Analyze Weekly Trade Journal and Calculate Metrics",
            status="pending",
            priority="high",
            preferred_time_slot="evening",
            scheduled_time=datetime.strptime("19:00:00", "%H:%M:%S").time(),
            estimated_duration_minutes=150,
            display_order=2,
        )
        Task.objects.create(
            subgoal=subgoal,
            title="Organize Trade Journal & Define Review Scope",
            status="pending",
            priority="high",
            preferred_time_slot="evening",
            scheduled_time=datetime.strptime("19:00:00", "%H:%M:%S").time(),
            estimated_duration_minutes=120,
            display_order=1,
        )

        task_list, created = get_or_create_today_task_list(self.user, target_date)
        self.assertTrue(created)
        evening_goal_titles = list(
            task_list.tasks.filter(item_type="goal_task", time_slot="evening")
            .order_by("display_order")
            .values_list("title", flat=True)
        )
        self.assertLess(
            evening_goal_titles.index("Organize Trade Journal & Define Review Scope"),
            evening_goal_titles.index("Analyze Weekly Trade Journal and Calculate Metrics"),
        )

    def test_generation_prefers_explicit_suggested_time_over_text_inference(self):
        target_date = timezone.localdate()
        goal, subgoal = self._create_goal_with_subgoal("Explicit Time Goal", priority="medium")
        Task.objects.create(
            subgoal=subgoal,
            title="Morning reading block",
            status="pending",
            priority="medium",
            estimated_duration_minutes=30,
            display_order=1,
        )
        HabitTracker.objects.create(
            user=self.user,
            name="Hydration Reminder",
            frequency="daily",
            is_active=True,
            estimated_minutes=10,
            suggested_time=datetime.strptime("07:00:00", "%H:%M:%S").time(),
            priority="medium",
        )

        task_list, created = get_or_create_today_task_list(self.user, target_date)
        self.assertTrue(created)
        morning_titles = list(
            task_list.tasks.filter(time_slot="morning").order_by("display_order").values_list("title", flat=True)
        )
        self.assertLess(morning_titles.index("Hydration Reminder"), morning_titles.index("Morning reading block"))

    def test_force_regenerate_keeps_deterministic_display_order(self):
        target_date = timezone.localdate()
        goal, subgoal = self._create_goal_with_subgoal("Deterministic Ordering Goal", priority="high")
        Task.objects.create(
            subgoal=subgoal,
            title="Analyze Weekly Trade Journal and Calculate Metrics",
            status="pending",
            priority="high",
            preferred_time_slot="evening",
            scheduled_time=datetime.strptime("19:00:00", "%H:%M:%S").time(),
            estimated_duration_minutes=150,
            display_order=2,
        )
        Task.objects.create(
            subgoal=subgoal,
            title="Organize Trade Journal & Define Review Scope",
            status="pending",
            priority="high",
            preferred_time_slot="evening",
            scheduled_time=datetime.strptime("19:00:00", "%H:%M:%S").time(),
            estimated_duration_minutes=120,
            display_order=1,
        )
        HabitTracker.objects.create(
            user=self.user,
            name="Sleep Preparation",
            description="Wind down and prepare for sleep.",
            frequency="daily",
            is_active=True,
            estimated_minutes=30,
            suggested_time=datetime.strptime("22:00:00", "%H:%M:%S").time(),
            time_slot="evening",
            priority="high",
        )

        first_list, first_created = get_or_create_today_task_list(self.user, target_date)
        regenerated_list, regenerated_created = get_or_create_today_task_list(
            self.user,
            target_date,
            force_regenerate=True,
        )

        self.assertTrue(first_created)
        self.assertTrue(regenerated_created)
        first_titles = list(first_list.tasks.order_by("display_order").values_list("title", flat=True))
        regenerated_titles = list(regenerated_list.tasks.order_by("display_order").values_list("title", flat=True))
        self.assertEqual(first_titles, regenerated_titles)
        self.assertEqual(
            first_list.schedule_constraints.get("organization_policy"),
            regenerated_list.schedule_constraints.get("organization_policy"),
        )

    def test_event_pre_buffer_is_applied_once_in_schedule_constraints(self):
        target_date = timezone.localdate()
        Event.objects.create(
            user=self.user,
            title="Buffered Event",
            description="One buffered event",
            event_type="one_time",
            start_at=datetime.fromisoformat(f"{target_date.isoformat()}T10:00:00+00:00"),
            end_at=datetime.fromisoformat(f"{target_date.isoformat()}T11:00:00+00:00"),
            is_all_day=False,
            timezone="UTC",
            recurrence=None,
            routine_constraint={
                "constraint_mode": "hard",
                "buffer_before_minutes": 15,
                "buffer_after_minutes": 10,
                "routine_policy": "block",
            },
        )

        occurrences = _get_event_occurrences_for_day(self.user, target_date)
        self.assertEqual(occurrences[0]["start_at"].isoformat(), f"{target_date.isoformat()}T10:00:00+00:00")
        constraints = _fetch_day_event_constraints(self.user, target_date, occurrences)
        self.assertEqual(
            constraints["occupied_windows"][0]["start_at"].isoformat(),
            f"{target_date.isoformat()}T09:45:00+00:00",
        )

    def test_force_regenerate_preserves_manual_tasks_and_removed_generated_items(self):
        target_date = timezone.localdate()
        goal, subgoal = self._create_goal_with_subgoal("Overlay Goal", priority="high")
        Task.objects.create(
            subgoal=subgoal,
            title="Generated focus task",
            status="pending",
            priority="high",
            estimated_duration_minutes=45,
            display_order=1,
        )

        first_list, created = get_or_create_today_task_list(self.user, target_date)
        self.assertTrue(created)
        generated_item = first_list.tasks.filter(goal_task__isnull=False).first()
        self.assertIsNotNone(generated_item)
        generated_item.removed_by_user = True
        generated_item.removed_at = timezone.now()
        generated_item.save(update_fields=["removed_by_user", "removed_at", "updated_at"])
        DailyTaskItem.objects.create(
            task_list=first_list,
            item_type="manual_task",
            title="Preserved manual task",
            priority="medium",
            estimated_minutes=25,
            display_order=999,
        )

        regenerated_list, regenerated_created = get_or_create_today_task_list(
            self.user,
            target_date,
            force_regenerate=True,
        )
        self.assertTrue(regenerated_created)

        preserved_manual = regenerated_list.tasks.filter(item_type="manual_task", title="Preserved manual task").first()
        self.assertIsNotNone(preserved_manual)
        preserved_generated = regenerated_list.tasks.get(goal_task_id=generated_item.goal_task_id)
        self.assertTrue(preserved_generated.removed_by_user)
        self.assertEqual(
            regenerated_list.schedule_constraints["regeneration_overlay"]["manual_tasks_preserved"],
            1,
        )
        self.assertEqual(
            regenerated_list.schedule_constraints["regeneration_overlay"]["removed_items_restored"],
            1,
        )

    def test_flex_day_profile_caps_actionable_non_event_work_to_two_items(self):
        target_date = timezone.localdate()
        goal, subgoal = self._create_goal_with_subgoal("Flex Load Goal", priority="high")
        for idx in range(1, 6):
            Task.objects.create(
                subgoal=subgoal,
                title=f"Flex task {idx}",
                status="pending",
                priority="high" if idx < 3 else "medium",
                estimated_duration_minutes=40,
                display_order=idx,
            )
        HabitTracker.objects.create(
            user=self.user,
            name="Flex habit",
            frequency="daily",
            is_active=True,
            estimated_minutes=20,
            priority="high",
        )
        HabitTracker.objects.create(
            user=self.user,
            name="Extra habit",
            frequency="daily",
            is_active=True,
            estimated_minutes=20,
            priority="medium",
        )

        task_list, created = get_or_create_today_task_list(self.user, target_date, day_mode="flex")
        self.assertTrue(created)

        actionable_count = task_list.tasks.filter(item_type__in=["habit", "goal_task"]).count()
        self.assertLessEqual(actionable_count, 2)
        self.assertEqual(task_list.schedule_constraints["day_mode"]["value"], "flex")
        self.assertEqual(task_list.schedule_constraints["fit_summary"]["fallback_strategy"], "flex_profile")

    def test_day_mode_carry_forward_across_dates_and_override(self):
        day_one = timezone.localdate()
        day_two = day_one + timedelta(days=1)
        day_three = day_one + timedelta(days=2)
        day_four = day_one + timedelta(days=3)
        goal, subgoal = self._create_goal_with_subgoal("Carry Forward Goal", priority="medium")
        Task.objects.create(
            subgoal=subgoal,
            title="Carry task",
            status="pending",
            priority="medium",
            estimated_duration_minutes=30,
            display_order=1,
        )

        list_day_one, _ = get_or_create_today_task_list(self.user, day_one, day_mode="flex")
        self.assertEqual(list_day_one.schedule_constraints["day_mode"]["value"], "flex")
        self.assertEqual(
            RoutineDayModeCheckIn.objects.get(user=self.user, date=day_one).source,
            "explicit",
        )

        list_day_two, _ = get_or_create_today_task_list(self.user, day_two)
        self.assertEqual(list_day_two.schedule_constraints["day_mode"]["value"], "flex")
        self.assertEqual(
            RoutineDayModeCheckIn.objects.get(user=self.user, date=day_two).source,
            "carry_forward",
        )

        list_day_three, _ = get_or_create_today_task_list(self.user, day_three, day_mode="focused")
        self.assertEqual(list_day_three.schedule_constraints["day_mode"]["value"], "focused")
        self.assertEqual(
            RoutineDayModeCheckIn.objects.get(user=self.user, date=day_three).source,
            "explicit",
        )

        list_day_four, _ = get_or_create_today_task_list(self.user, day_four)
        self.assertEqual(list_day_four.schedule_constraints["day_mode"]["value"], "focused")
        self.assertEqual(
            RoutineDayModeCheckIn.objects.get(user=self.user, date=day_four).source,
            "carry_forward",
        )

    def test_day_mode_resolution_keeps_single_checkin_per_date(self):
        day_one = timezone.localdate()
        day_two = day_one + timedelta(days=1)

        _resolve_and_persist_day_mode(self.user, day_one, explicit_day_mode="flex")
        first = _resolve_and_persist_day_mode(self.user, day_two, explicit_day_mode=None)
        second = _resolve_and_persist_day_mode(self.user, day_two, explicit_day_mode=None)

        self.assertEqual(first["day_mode"], "flex")
        self.assertEqual(second["day_mode"], "flex")
        self.assertEqual(
            RoutineDayModeCheckIn.objects.filter(user=self.user, date=day_two).count(),
            1,
        )
        self.assertEqual(
            RoutineDayModeCheckIn.objects.get(user=self.user, date=day_two).source,
            "carry_forward",
        )

    def test_daily_generation_balances_tasks_across_multiple_active_goals(self):
        target_date = timezone.localdate()
        goals = []

        g1, sg1 = self._create_goal_with_subgoal("Goal A", priority="high", status="in_progress")
        goals.append(g1)
        for idx in range(1, 21):
            Task.objects.create(
                subgoal=sg1,
                title=f"A{idx}",
                status="pending",
                priority="high",
                estimated_duration_minutes=30,
                display_order=idx,
            )

        g2, sg2 = self._create_goal_with_subgoal("Goal B", priority="high", status="not_started")
        goals.append(g2)
        for idx in range(1, 10):
            Task.objects.create(
                subgoal=sg2,
                title=f"B{idx}",
                status="pending",
                priority="medium",
                estimated_duration_minutes=30,
                display_order=idx,
            )

        g3, sg3 = self._create_goal_with_subgoal("Goal C", priority="medium", status="in_progress")
        goals.append(g3)
        for idx in range(1, 7):
            Task.objects.create(
                subgoal=sg3,
                title=f"C{idx}",
                status="pending",
                priority="low",
                estimated_duration_minutes=30,
                display_order=idx,
            )

        task_list, created = get_or_create_today_task_list(self.user, target_date)
        self.assertTrue(created)

        goal_items = list(task_list.tasks.filter(item_type="goal_task").order_by("display_order"))
        self.assertEqual(len(goal_items), 15)

        present_goal_ids = {item.related_goal_id for item in goal_items if item.related_goal_id}
        self.assertTrue(g1.id in present_goal_ids)
        self.assertTrue(g2.id in present_goal_ids)
        self.assertTrue(g3.id in present_goal_ids)

    def test_daily_generation_round_robin_fills_remaining_slots(self):
        target_date = timezone.localdate()

        g_high, sg_high = self._create_goal_with_subgoal("High Goal", priority="high", status="in_progress")
        g_med, sg_med = self._create_goal_with_subgoal("Medium Goal", priority="medium", status="in_progress")
        g_low, sg_low = self._create_goal_with_subgoal("Low Goal", priority="low", status="in_progress")

        # Create out of order to verify display_order-based deterministic sorting.
        Task.objects.create(subgoal=sg_high, title="H2", status="pending", priority="high", estimated_duration_minutes=30, display_order=2)
        Task.objects.create(subgoal=sg_high, title="H1", status="pending", priority="high", estimated_duration_minutes=30, display_order=1)
        Task.objects.create(subgoal=sg_high, title="H3", status="pending", priority="high", estimated_duration_minutes=30, display_order=3)

        Task.objects.create(subgoal=sg_med, title="M2", status="pending", priority="medium", estimated_duration_minutes=30, display_order=2)
        Task.objects.create(subgoal=sg_med, title="M1", status="pending", priority="medium", estimated_duration_minutes=30, display_order=1)

        Task.objects.create(subgoal=sg_low, title="L1", status="pending", priority="low", estimated_duration_minutes=30, display_order=1)

        task_list, created = get_or_create_today_task_list(self.user, target_date)
        self.assertTrue(created)

        ordered_titles = list(
            task_list.tasks.filter(item_type="goal_task").order_by("display_order").values_list("title", flat=True)
        )
        self.assertEqual(ordered_titles, ["H1", "M1", "L1", "H2", "M2", "H3"])

        ordered_goals = list(
            task_list.tasks.filter(item_type="goal_task").order_by("display_order").values_list("related_goal_id", flat=True)
        )
        self.assertEqual(
            ordered_goals,
            [g_high.id, g_med.id, g_low.id, g_high.id, g_med.id, g_high.id],
        )

    def test_selector_prioritizes_prerequisites_within_goal(self):
        goal, subgoal = self._create_goal_with_subgoal("Prerequisite Goal", priority="high")
        non_prerequisite = Task.objects.create(
            subgoal=subgoal,
            title="Regular follow-up task",
            status="pending",
            priority="high",
            estimated_duration_minutes=30,
            display_order=1,
            difficulty_level=2,
            is_prerequisite=False,
        )
        prerequisite = Task.objects.create(
            subgoal=subgoal,
            title="Foundation prerequisite task",
            status="pending",
            priority="high",
            estimated_duration_minutes=30,
            display_order=2,
            difficulty_level=2,
            is_prerequisite=True,
        )

        selected = _select_balanced_goal_tasks(user=self.user, limit=2)

        self.assertEqual([task.id for task in selected], [prerequisite.id, non_prerequisite.id])
        self.assertEqual(goal.id, selected[0].subgoal.milestone.goal_id)

    def test_routine_generation_stays_stable_without_rie_signal(self):
        target_date = timezone.localdate()
        goal, subgoal = self._create_goal_with_subgoal("No Signal Goal", priority="high")
        longer_task = Task.objects.create(
            subgoal=subgoal,
            title="Longer default-first task",
            status="pending",
            priority="high",
            estimated_duration_minutes=90,
            display_order=1,
        )
        shorter_task = Task.objects.create(
            subgoal=subgoal,
            title="Shorter follow-up task",
            status="pending",
            priority="high",
            estimated_duration_minutes=20,
            display_order=2,
        )

        self.assertIsNone(_load_rie_signal_for_goal(goal.id))

        task_list, created = get_or_create_today_task_list(self.user, target_date)

        self.assertTrue(created)
        ordered_ids = list(
            task_list.tasks.filter(item_type="goal_task").order_by("display_order").values_list("goal_task_id", flat=True)
        )
        self.assertEqual(ordered_ids[:2], [longer_task.id, shorter_task.id])

    def test_routine_generation_loads_and_applies_rie_signal(self):
        target_date = timezone.localdate()
        goal, subgoal = self._create_goal_with_subgoal("Signal Guided Goal", priority="high")
        longer_task = Task.objects.create(
            subgoal=subgoal,
            title="Longer task",
            status="pending",
            priority="high",
            estimated_duration_minutes=90,
            display_order=1,
        )
        shorter_task = Task.objects.create(
            subgoal=subgoal,
            title="Shorter task",
            status="pending",
            priority="high",
            estimated_duration_minutes=20,
            display_order=2,
        )

        session = GIESession.objects.create(
            user=self.user,
            goal_text=goal.title,
            goal_domain=GIESession.DOMAIN_CAREER,
            status=GIESession.STATUS_FINALIZED,
            phase=GIESession.PHASE_FINALIZED,
        )
        expected_signal = {
            "goal_priority": "high",
            "confirmed_habits": [],
            "suggested_sequence_order": [],
            "estimated_daily_capacity_minutes": 30,
        }
        GIEPlanSnapshot.objects.create(
            session=session,
            status=GIEPlanSnapshot.STATUS_FINALIZED,
            goal_summary=goal.description,
            milestones=[],
            weekly_routine_guidance=[],
            rie_signal=expected_signal,
        )

        loaded_signal = _load_rie_signal_for_goal(goal.id)

        self.assertEqual(loaded_signal, expected_signal)

        task_list, created = get_or_create_today_task_list(self.user, target_date)

        self.assertTrue(created)
        ordered_ids = list(
            task_list.tasks.filter(item_type="goal_task").order_by("display_order").values_list("goal_task_id", flat=True)
        )
        self.assertEqual(ordered_ids[:2], [shorter_task.id, longer_task.id])

    def test_selector_applies_deadline_urgency_across_goal_buckets(self):
        today = timezone.localdate()
        near_goal, near_subgoal = self._create_goal_with_subgoal(
            "Near Deadline Goal",
            priority="high",
            target_date=today + timedelta(days=3),
        )
        far_goal, far_subgoal = self._create_goal_with_subgoal(
            "Far Deadline Goal",
            priority="high",
            target_date=today + timedelta(days=90),
        )
        near_task = Task.objects.create(
            subgoal=near_subgoal,
            title="Near deadline task",
            status="pending",
            priority="medium",
            estimated_duration_minutes=30,
            display_order=1,
        )
        far_task = Task.objects.create(
            subgoal=far_subgoal,
            title="Far deadline task",
            status="pending",
            priority="medium",
            estimated_duration_minutes=30,
            display_order=1,
        )

        selected = _select_balanced_goal_tasks(user=self.user, limit=2)

        self.assertEqual([task.id for task in selected], [near_task.id, far_task.id])
        self.assertEqual([task.subgoal.milestone.goal_id for task in selected], [near_goal.id, far_goal.id])

    def test_selector_penalizes_higher_difficulty_tasks(self):
        _, subgoal = self._create_goal_with_subgoal("Difficulty Goal", priority="medium")
        hard_task = Task.objects.create(
            subgoal=subgoal,
            title="Hard task",
            status="pending",
            priority="medium",
            estimated_duration_minutes=45,
            display_order=1,
            difficulty_level=5,
        )
        easier_task = Task.objects.create(
            subgoal=subgoal,
            title="Easier task",
            status="pending",
            priority="medium",
            estimated_duration_minutes=45,
            display_order=2,
            difficulty_level=1,
        )

        selected = _select_balanced_goal_tasks(user=self.user, limit=2)

        self.assertEqual([task.id for task in selected], [easier_task.id, hard_task.id])

    def test_selector_deprioritizes_recently_skipped_tasks_when_alternatives_exist(self):
        _, subgoal = self._create_goal_with_subgoal("Adaptive Recovery Goal", priority="high")
        repeated_task = Task.objects.create(
            subgoal=subgoal,
            title="Large skipped task",
            status="pending",
            priority="high",
            estimated_duration_minutes=90,
            display_order=1,
            difficulty_level=4,
        )
        alternative_task = Task.objects.create(
            subgoal=subgoal,
            title="Smaller next step",
            status="pending",
            priority="high",
            estimated_duration_minutes=25,
            display_order=2,
            difficulty_level=1,
        )

        previous_date = timezone.localdate() - timedelta(days=1)
        previous_list = DailyTaskList.objects.create(user=self.user, date=previous_date)
        skipped_item = DailyTaskItem.objects.create(
            task_list=previous_list,
            item_type="goal_task",
            goal_task=repeated_task,
            related_goal=repeated_task.subgoal.milestone.goal,
            title=repeated_task.title,
            description="Previously surfaced and skipped",
            priority="high",
            estimated_minutes=90,
            display_order=0,
        )
        skipped_item.mark_skipped(reason="Too difficult and I got stuck")

        selected = _select_balanced_goal_tasks(user=self.user, limit=2)

        self.assertEqual([task.id for task in selected], [alternative_task.id, repeated_task.id])

    def test_selector_promotes_subgoal_momentum_after_recent_completion(self):
        _, momentum_subgoal = self._create_goal_with_subgoal("Momentum Goal", priority="high")
        _, competing_subgoal = self._create_goal_with_subgoal("Competing Goal", priority="high")
        finished_step = Task.objects.create(
            subgoal=momentum_subgoal,
            title="Completed setup step",
            status="completed",
            priority="high",
            estimated_duration_minutes=20,
            display_order=1,
        )
        next_step = Task.objects.create(
            subgoal=momentum_subgoal,
            title="Next momentum step",
            status="pending",
            priority="high",
            estimated_duration_minutes=30,
            display_order=2,
        )
        competing_task = Task.objects.create(
            subgoal=competing_subgoal,
            title="Unrelated competing step",
            status="pending",
            priority="high",
            estimated_duration_minutes=30,
            display_order=1,
        )

        previous_date = timezone.localdate() - timedelta(days=1)
        previous_list = DailyTaskList.objects.create(user=self.user, date=previous_date)
        completed_item = DailyTaskItem.objects.create(
            task_list=previous_list,
            item_type="goal_task",
            goal_task=finished_step,
            related_goal=finished_step.subgoal.milestone.goal,
            title=finished_step.title,
            description="Completed yesterday",
            priority="high",
            estimated_minutes=20,
            display_order=0,
            is_completed=True,
            completed_at=timezone.now(),
        )
        previous_list.update_progress()

        selected = _select_balanced_goal_tasks(user=self.user, limit=2)

        self.assertEqual([task.id for task in selected], [next_step.id, competing_task.id])

    def test_selector_excludes_completed_milestones_from_candidates(self):
        _, active_subgoal = self._create_goal_with_subgoal(
            "Active Milestone Goal",
            priority="medium",
            milestone_status="in_progress",
        )
        _, completed_subgoal = self._create_goal_with_subgoal(
            "Completed Milestone Goal",
            priority="high",
            milestone_status="completed",
        )
        active_task = Task.objects.create(
            subgoal=active_subgoal,
            title="Active task",
            status="pending",
            priority="medium",
            estimated_duration_minutes=30,
            display_order=1,
        )
        Task.objects.create(
            subgoal=completed_subgoal,
            title="Completed milestone task",
            status="pending",
            priority="high",
            estimated_duration_minutes=30,
            display_order=1,
            is_prerequisite=True,
        )

        selected = _select_balanced_goal_tasks(user=self.user, limit=5)

        self.assertEqual([task.id for task in selected], [active_task.id])

    def test_daily_generation_scored_selection_still_balances_across_goals(self):
        target_date = timezone.localdate()
        urgent_goal, urgent_subgoal = self._create_goal_with_subgoal(
            "Urgent Goal",
            priority="high",
            status="in_progress",
            target_date=target_date + timedelta(days=2),
        )
        steady_goal, steady_subgoal = self._create_goal_with_subgoal(
            "Steady Goal",
            priority="high",
            status="in_progress",
            target_date=target_date + timedelta(days=90),
        )
        support_goal, support_subgoal = self._create_goal_with_subgoal(
            "Support Goal",
            priority="medium",
            status="in_progress",
            target_date=target_date + timedelta(days=45),
        )

        for idx in range(1, 8):
            Task.objects.create(
                subgoal=urgent_subgoal,
                title=f"Urgent {idx}",
                status="pending",
                priority="high",
                estimated_duration_minutes=30,
                display_order=idx,
                is_prerequisite=idx <= 3,
                difficulty_level=1 if idx <= 3 else 4,
            )
        for idx in range(1, 5):
            Task.objects.create(
                subgoal=steady_subgoal,
                title=f"Steady {idx}",
                status="pending",
                priority="medium",
                estimated_duration_minutes=30,
                display_order=idx,
                difficulty_level=2,
            )
        for idx in range(1, 4):
            Task.objects.create(
                subgoal=support_subgoal,
                title=f"Support {idx}",
                status="pending",
                priority="low",
                estimated_duration_minutes=30,
                display_order=idx,
                difficulty_level=1,
            )

        task_list, created = get_or_create_today_task_list(self.user, target_date)
        self.assertTrue(created)

        goal_items = list(task_list.tasks.filter(item_type="goal_task").order_by("display_order"))
        present_goal_ids = {item.related_goal_id for item in goal_items if item.related_goal_id}
        self.assertTrue(urgent_goal.id in present_goal_ids)
        self.assertTrue(steady_goal.id in present_goal_ids)
        self.assertTrue(support_goal.id in present_goal_ids)

    def test_generation_keeps_adaptive_adjustments_with_scored_selection(self):
        target_date = timezone.localdate()
        if target_date.weekday() == 6:
            target_date = target_date + timedelta(days=1)

        _, subgoal = self._create_goal_with_subgoal(
            "Adaptive Scored Goal",
            priority="high",
            status="in_progress",
        )
        lower_ranked = Task.objects.create(
            subgoal=subgoal,
            title="Later regular task",
            description="Regular follow-up work",
            status="pending",
            priority="high",
            estimated_duration_minutes=100,
            display_order=1,
            difficulty_level=4,
        )
        scored_task = Task.objects.create(
            subgoal=subgoal,
            title="Prerequisite recovery task",
            description="Important prerequisite step",
            status="pending",
            priority="high",
            estimated_duration_minutes=60,
            display_order=2,
            difficulty_level=1,
            is_prerequisite=True,
        )

        for offset in range(1, 6):
            missed_date = target_date - timedelta(days=offset)
            DailyTaskList.objects.create(
                user=self.user,
                date=missed_date,
                total_tasks=3,
                completed_tasks=0,
                completion_percentage=0,
                is_fully_completed=False,
                status="pending",
            )

        task_list, created = get_or_create_today_task_list(self.user, target_date)
        self.assertTrue(created)

        goal_items = list(task_list.tasks.filter(item_type="goal_task").order_by("display_order"))
        self.assertGreaterEqual(len(goal_items), 2)
        self.assertEqual([item.goal_task_id for item in goal_items[:2]], [scored_task.id, lower_ranked.id])
        self.assertEqual(goal_items[0].priority, "medium")
        self.assertEqual(goal_items[0].estimated_minutes, 43)

    def test_habits_still_included_daily_after_completion(self):
        day_one = timezone.localdate()
        day_two = day_one + timedelta(days=1)

        habit = HabitTracker.objects.create(
            user=self.user,
            name="Daily Focus Session",
            frequency="daily",
            is_active=True,
            estimated_minutes=20,
            priority="medium",
        )

        day_one_list, _ = get_or_create_today_task_list(self.user, day_one)
        habit_item_day_one = day_one_list.tasks.filter(item_type="habit", habit=habit).first()
        self.assertIsNotNone(habit_item_day_one)

        habit_item_day_one.mark_completed(notes="done", actual_minutes=20)

        day_two_list, _ = get_or_create_today_task_list(self.user, day_two)
        habit_item_day_two = day_two_list.tasks.filter(item_type="habit", habit=habit).first()
        self.assertIsNotNone(habit_item_day_two)
        self.assertFalse(habit_item_day_two.is_completed)

    def test_generation_applies_weekly_friction_adjustments_from_skip_reasons(self):
        day_one = timezone.localdate()
        target_date = day_one + timedelta(days=1)

        goal, subgoal = self._create_goal_with_subgoal("Friction Goal", priority="high", status="in_progress")
        task = Task.objects.create(
            subgoal=subgoal,
            title="Deep focus implementation",
            description="Ship the implementation",
            status="pending",
            priority="high",
            estimated_duration_minutes=100,
            display_order=1,
        )

        day_one_list = DailyTaskList.objects.create(user=self.user, date=day_one)
        skipped_item = DailyTaskItem.objects.create(
            task_list=day_one_list,
            item_type="goal_task",
            goal_task=task,
            related_goal=goal,
            title="Previous attempt",
            description="Attempted but skipped",
            priority="high",
            estimated_minutes=100,
            display_order=0,
        )
        skipped_item.mark_skipped(reason="No time due to meetings and overload")

        # Add another skipped item to cross the 2-skip threshold.
        extra_skipped = DailyTaskItem.objects.create(
            task_list=day_one_list,
            item_type="goal_task",
            related_goal=goal,
            title="Secondary task",
            description="Skipped due to schedule",
            priority="medium",
            estimated_minutes=60,
            display_order=1,
        )
        extra_skipped.mark_skipped(reason="Busy work schedule")

        task_list, created = get_or_create_today_task_list(self.user, target_date)
        self.assertTrue(created)

        generated_item = task_list.tasks.filter(item_type="goal_task", goal_task=task).first()
        self.assertIsNotNone(generated_item)
        # 100 minutes with time-pressure multiplier (0.85) becomes 85.
        self.assertEqual(generated_item.estimated_minutes, 85)

    def test_generation_uses_negative_journal_signals_to_reduce_load_and_tone(self):
        day_one = timezone.localdate()
        target_date = day_one + timedelta(days=1)

        goal, subgoal = self._create_goal_with_subgoal("Journal Recovery Goal", priority="high", status="in_progress")
        task = Task.objects.create(
            subgoal=subgoal,
            title="Ship sprint draft",
            description="Draft and submit sprint deliverable",
            status="pending",
            priority="high",
            estimated_duration_minutes=100,
            display_order=1,
        )

        JournalEntry.objects.create(
            user=self.user,
            entry_date=day_one - timedelta(days=1),
            reflection_raw="I felt overwhelmed and distracted.",
            struggle_raw="I procrastinated and spent too much time on social media.",
            tomorrow_priority_raw="Just do a small first step.",
            gratitude_raw="Grateful for rest.",
            sentiment_label=JournalEntry.SENTIMENT_NEGATIVE,
            sentiment_score=-0.6,
            tags=["procrastination", "doomscrolling"],
            locked_at=timezone.now() + timedelta(days=1),
        )
        JournalEntry.objects.create(
            user=self.user,
            entry_date=day_one,
            reflection_raw="Energy was low and focus was difficult.",
            struggle_raw="I delayed important work again.",
            tomorrow_priority_raw="Keep tasks simple tomorrow.",
            gratitude_raw="Grateful for another chance.",
            sentiment_label=JournalEntry.SENTIMENT_NEGATIVE,
            sentiment_score=-0.4,
            tags=["distraction"],
            locked_at=timezone.now() + timedelta(days=1),
        )

        task_list, created = get_or_create_today_task_list(self.user, target_date)
        self.assertTrue(created)

        generated_item = task_list.tasks.filter(item_type="goal_task", goal_task=task).first()
        self.assertIsNotNone(generated_item)
        self.assertEqual(generated_item.priority, "medium")
        self.assertEqual(generated_item.estimated_minutes, 81)
        self.assertIn("Friction adjustment: start with a 15-minute first step.", generated_item.description)
        self.assertIn("Journal tone: keep today gentle and momentum-focused.", generated_item.description)

    def test_generation_uses_positive_journal_signals_for_challenge_tone(self):
        day_one = timezone.localdate()
        target_date = day_one + timedelta(days=1)

        _, subgoal = self._create_goal_with_subgoal("Journal Momentum Goal", priority="high", status="in_progress")
        task = Task.objects.create(
            subgoal=subgoal,
            title="Prepare investor update",
            description="Summarize progress for stakeholders",
            status="pending",
            priority="high",
            estimated_duration_minutes=100,
            display_order=1,
        )

        JournalEntry.objects.create(
            user=self.user,
            entry_date=day_one - timedelta(days=1),
            reflection_raw="I made great progress and felt focused.",
            struggle_raw="Minor blocker but resolved quickly.",
            tomorrow_priority_raw="Push the next meaningful milestone.",
            gratitude_raw="Grateful and motivated.",
            sentiment_label=JournalEntry.SENTIMENT_POSITIVE,
            sentiment_score=0.5,
            tags=["momentum"],
            locked_at=timezone.now() + timedelta(days=1),
        )
        JournalEntry.objects.create(
            user=self.user,
            entry_date=day_one,
            reflection_raw="Strong execution day with confident decisions.",
            struggle_raw="No major blockers.",
            tomorrow_priority_raw="Take a stretch step tomorrow.",
            gratitude_raw="Happy with progress.",
            sentiment_label=JournalEntry.SENTIMENT_POSITIVE,
            sentiment_score=0.4,
            tags=["confidence"],
            locked_at=timezone.now() + timedelta(days=1),
        )

        task_list, created = get_or_create_today_task_list(self.user, target_date)
        self.assertTrue(created)

        generated_item = task_list.tasks.filter(item_type="goal_task", goal_task=task).first()
        self.assertIsNotNone(generated_item)
        self.assertEqual(generated_item.priority, "high")
        self.assertEqual(generated_item.estimated_minutes, 105)
        self.assertIn("Journal tone: push slightly beyond comfort with focus.", generated_item.description)

    def test_generation_triggers_five_day_miss_recovery(self):
        target_date = timezone.localdate()
        if target_date.weekday() == 6:
            target_date = target_date + timedelta(days=1)
        goal, subgoal = self._create_goal_with_subgoal(
            "Adaptive Recovery Goal",
            priority="high",
            status="in_progress",
        )
        task = Task.objects.create(
            subgoal=subgoal,
            title="Important recovery task",
            description="Complete a focused recovery step",
            status="pending",
            priority="high",
            estimated_duration_minutes=100,
            display_order=1,
        )

        for offset in range(1, 6):
            missed_date = target_date - timedelta(days=offset)
            DailyTaskList.objects.create(
                user=self.user,
                date=missed_date,
                total_tasks=3,
                completed_tasks=0,
                completion_percentage=0,
                is_fully_completed=False,
                status="pending",
            )

        task_list, created = get_or_create_today_task_list(self.user, target_date)
        self.assertTrue(created)

        generated_item = task_list.tasks.filter(item_type="goal_task", goal_task=task).first()
        self.assertIsNotNone(generated_item)
        self.assertEqual(generated_item.estimated_minutes, 71)
        self.assertEqual(generated_item.priority, "medium")

        adaptive_state = AdaptiveRoadmapState.objects.get(user=self.user)
        self.assertEqual(adaptive_state.consecutive_miss_days, 5)

    def test_generation_triggers_sunday_rebuild_once_per_sunday(self):
        today = timezone.localdate()
        days_until_sunday = (6 - today.weekday()) % 7
        target_date = today + timedelta(days=days_until_sunday)

        _, subgoal = self._create_goal_with_subgoal(
            "Sunday Rebuild Goal",
            priority="high",
            status="in_progress",
        )
        task = Task.objects.create(
            subgoal=subgoal,
            title="Sunday intensity task",
            description="Planned task for Sunday generation",
            status="pending",
            priority="high",
            estimated_duration_minutes=100,
            display_order=1,
        )

        task_list, created = get_or_create_today_task_list(self.user, target_date)
        self.assertTrue(created)
        generated_item = task_list.tasks.filter(item_type="goal_task", goal_task=task).first()
        self.assertIsNotNone(generated_item)
        self.assertEqual(generated_item.estimated_minutes, 90)

        adaptive_state = AdaptiveRoadmapState.objects.get(user=self.user)
        self.assertEqual(adaptive_state.last_sunday_rebuild_date, target_date)

    def test_generation_progressive_and_reversible_scaling_levels(self):
        target_date = timezone.localdate()
        if target_date.weekday() == 6:
            target_date = target_date + timedelta(days=1)

        # Build consecutive success run (3 days) to increase scale level.
        for offset in range(1, 4):
            success_date = target_date - timedelta(days=offset)
            DailyTaskList.objects.create(
                user=self.user,
                date=success_date,
                total_tasks=3,
                completed_tasks=3,
                completion_percentage=100,
                is_fully_completed=True,
                status="completed",
            )

        _, subgoal = self._create_goal_with_subgoal(
            "Scaling Goal",
            priority="high",
            status="in_progress",
        )
        scaling_task = Task.objects.create(
            subgoal=subgoal,
            title="Scaling candidate",
            description="Track adaptive scale changes",
            status="pending",
            priority="high",
            estimated_duration_minutes=100,
            display_order=1,
        )

        first_list, first_created = get_or_create_today_task_list(self.user, target_date)
        self.assertTrue(first_created)
        first_item = first_list.tasks.filter(item_type="goal_task", goal_task=scaling_task).first()
        self.assertIsNotNone(first_item)
        self.assertEqual(first_item.estimated_minutes, 105)

        adaptive_state = AdaptiveRoadmapState.objects.get(user=self.user)
        self.assertEqual(adaptive_state.current_scale_level, 1)

        # Build consecutive miss run to reverse scale on a later date.
        reverse_date = target_date + timedelta(days=3)
        if reverse_date.weekday() == 6:
            reverse_date = reverse_date + timedelta(days=1)
        for offset in range(1, 4):
            missed_date = reverse_date - timedelta(days=offset)
            DailyTaskList.objects.update_or_create(
                user=self.user,
                date=missed_date,
                defaults={
                    "total_tasks": 3,
                    "completed_tasks": 0,
                    "completion_percentage": 0,
                    "is_fully_completed": False,
                    "status": "pending",
                },
            )

        reverse_list, reverse_created = get_or_create_today_task_list(self.user, reverse_date)
        self.assertTrue(reverse_created)
        reverse_item = reverse_list.tasks.filter(item_type="goal_task", goal_task=scaling_task).first()
        self.assertIsNotNone(reverse_item)
        self.assertEqual(reverse_item.estimated_minutes, 100)

        adaptive_state.refresh_from_db()
        self.assertEqual(adaptive_state.current_scale_level, 0)

    def test_generation_includes_adaptive_metadata_contract_in_schedule_constraints(self):
        target_date = timezone.localdate()
        if target_date.weekday() == 6:
            target_date = target_date + timedelta(days=1)

        _, subgoal = self._create_goal_with_subgoal(
            "Adaptive Metadata Goal",
            priority="medium",
            status="in_progress",
        )
        Task.objects.create(
            subgoal=subgoal,
            title="Metadata task",
            status="pending",
            priority="medium",
            estimated_duration_minutes=40,
            display_order=1,
        )

        task_list, created = get_or_create_today_task_list(self.user, target_date)
        self.assertTrue(created)

        adaptive = task_list.schedule_constraints.get("adaptive_roadmap")
        self.assertIsNotNone(adaptive)
        self.assertEqual(adaptive["target_date"], target_date.isoformat())
        self.assertIn("state", adaptive)
        self.assertIn("triggers", adaptive)
        self.assertIn("adjustments", adaptive)
        self.assertIn("recommendations", adaptive)
        self.assertEqual(adaptive["policy"]["scale_change_cooldown_days"], 2)
        self.assertEqual(adaptive["policy"]["miss_recovery_threshold_days"], 5)

    def test_adaptive_scale_cooldown_transition_boundaries(self):
        target_date = timezone.localdate()
        if target_date.weekday() == 6:
            target_date = target_date + timedelta(days=1)

        for offset in range(1, 4):
            success_date = target_date - timedelta(days=offset)
            DailyTaskList.objects.create(
                user=self.user,
                date=success_date,
                total_tasks=2,
                completed_tasks=2,
                completion_percentage=100,
                is_fully_completed=True,
                status="completed",
            )

        state, _ = AdaptiveRoadmapState.objects.get_or_create(user=self.user)
        state.current_scale_level = 0
        state.last_scale_change_date = target_date - timedelta(days=1)
        state.save(update_fields=["current_scale_level", "last_scale_change_date", "updated_at"])

        blocked = build_adaptive_roadmap_adjustment(self.user, target_date)
        self.assertEqual(blocked["state"]["current_scale_level"], 0)

        state.refresh_from_db()
        state.last_scale_change_date = target_date - timedelta(days=2)
        state.save(update_fields=["last_scale_change_date", "updated_at"])

        allowed = build_adaptive_roadmap_adjustment(self.user, target_date)
        self.assertEqual(allowed["state"]["current_scale_level"], 1)

    def test_adaptive_weekly_reset_anchor_resets_on_iso_week_change(self):
        target_date = timezone.localdate()
        previous_week_anchor = target_date - timedelta(days=7)

        state, _ = AdaptiveRoadmapState.objects.get_or_create(user=self.user)
        state.weekly_reset_anchor = previous_week_anchor
        state.weekly_miss_days = 4
        state.save(update_fields=["weekly_reset_anchor", "weekly_miss_days", "updated_at"])

        adjustment = build_adaptive_roadmap_adjustment(self.user, target_date)
        state.refresh_from_db()

        self.assertEqual(state.weekly_reset_anchor, target_date)
        self.assertEqual(state.weekly_miss_days, 0)
        self.assertEqual(adjustment["state"]["weekly_miss_days"], 0)

    def test_adaptive_scale_clamps_at_min_and_max_levels(self):
        target_date = timezone.localdate()

        upper_state, _ = AdaptiveRoadmapState.objects.get_or_create(user=self.user)
        upper_state.current_scale_level = 3
        upper_state.last_scale_change_date = target_date - timedelta(days=10)
        upper_state.save(update_fields=["current_scale_level", "last_scale_change_date", "updated_at"])

        for offset in range(1, 4):
            success_date = target_date - timedelta(days=offset)
            DailyTaskList.objects.update_or_create(
                user=self.user,
                date=success_date,
                defaults={
                    "total_tasks": 1,
                    "completed_tasks": 1,
                    "completion_percentage": 100,
                    "is_fully_completed": True,
                    "status": "completed",
                },
            )

        upper_adjustment = build_adaptive_roadmap_adjustment(self.user, target_date)
        self.assertEqual(upper_adjustment["state"]["current_scale_level"], 3)

        lower_user = CustomUser.objects.create_user(
            email="adaptive-lower-bound@test.com",
            password="Password@123",
        )
        lower_state, _ = AdaptiveRoadmapState.objects.get_or_create(user=lower_user)
        lower_state.current_scale_level = -3
        lower_state.last_scale_change_date = target_date - timedelta(days=10)
        lower_state.save(update_fields=["current_scale_level", "last_scale_change_date", "updated_at"])

        for offset in range(1, 6):
            missed_date = target_date - timedelta(days=offset)
            DailyTaskList.objects.create(
                user=lower_user,
                date=missed_date,
                total_tasks=2,
                completed_tasks=0,
                completion_percentage=0,
                is_fully_completed=False,
                status="pending",
            )

        lower_adjustment = build_adaptive_roadmap_adjustment(lower_user, target_date)
        self.assertEqual(lower_adjustment["state"]["current_scale_level"], -3)
        self.assertEqual(lower_adjustment["adjustments"]["minutes_multiplier"], 0.7)

    def test_repeated_same_day_generation_is_deterministic_without_force_regenerate(self):
        target_date = timezone.localdate()
        if target_date.weekday() == 6:
            target_date = target_date + timedelta(days=1)

        _, subgoal = self._create_goal_with_subgoal(
            "Determinism Goal",
            priority="high",
            status="in_progress",
        )
        Task.objects.create(
            subgoal=subgoal,
            title="Deterministic task",
            status="pending",
            priority="high",
            estimated_duration_minutes=60,
            display_order=1,
        )
        HabitTracker.objects.create(
            user=self.user,
            name="Daily consistency",
            frequency="daily",
            is_active=True,
            estimated_minutes=20,
            priority="medium",
        )

        first_list, first_created = get_or_create_today_task_list(self.user, target_date)
        second_list, second_created = get_or_create_today_task_list(self.user, target_date)

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first_list.id, second_list.id)
        self.assertEqual(first_list.tasks.count(), second_list.tasks.count())
        self.assertEqual(
            first_list.schedule_constraints.get("adaptive_roadmap"),
            second_list.schedule_constraints.get("adaptive_roadmap"),
        )

    def test_force_regenerate_keeps_deterministic_motivation_and_mantra(self):
        target_date = timezone.localdate()
        goal, subgoal = self._create_goal_with_subgoal("Deterministic Motivation Goal", priority="high")
        goal.target_date = target_date + timedelta(days=14)
        goal.save(update_fields=["target_date", "updated_at"])
        Task.objects.create(
            subgoal=subgoal,
            title="Finalize the investor update",
            status="pending",
            priority="high",
            estimated_duration_minutes=75,
            display_order=1,
        )
        HabitTracker.objects.create(
            user=self.user,
            name="Morning review",
            frequency="daily",
            is_active=True,
            estimated_minutes=15,
            priority="medium",
        )

        first_list, first_created = get_or_create_today_task_list(self.user, target_date)
        regenerated_list, regenerated_created = get_or_create_today_task_list(
            self.user,
            target_date,
            force_regenerate=True,
        )

        self.assertTrue(first_created)
        self.assertTrue(regenerated_created)
        self.assertTrue(first_list.daily_motivation)
        self.assertTrue(first_list.daily_mantra)
        self.assertEqual(first_list.daily_motivation, regenerated_list.daily_motivation)
        self.assertEqual(first_list.daily_mantra, regenerated_list.daily_mantra)

    def test_generator_uses_recovery_and_stretch_deadline_signals(self):
        target_date = timezone.localdate()
        stretch_goal, stretch_subgoal = self._create_goal_with_subgoal("Stretch Goal", priority="high")
        stretch_goal.primary_category = "career"
        stretch_goal.target_date = target_date + timedelta(days=3)
        stretch_goal.save(update_fields=["primary_category", "target_date", "updated_at"])
        stretch_task = Task.objects.create(
            subgoal=stretch_subgoal,
            title="Ship deadline deliverable",
            status="pending",
            priority="high",
            estimated_duration_minutes=120,
            display_order=1,
        )

        recovery_goal, recovery_subgoal = self._create_goal_with_subgoal("Recovery Goal", priority="medium")
        recovery_goal.primary_category = "health"
        recovery_goal.target_date = target_date + timedelta(days=30)
        recovery_goal.save(update_fields=["primary_category", "target_date", "updated_at"])
        recovery_task = Task.objects.create(
            subgoal=recovery_subgoal,
            title="Restore baseline workout",
            status="pending",
            priority="medium",
            estimated_duration_minutes=30,
            display_order=1,
        )

        generator = DailyRoutineGenerator()
        stretch_result = generator.generate_motivation_and_mantra(
            user_context={"streak_days": 5, "current_scale_level": 2},
            goal_tasks=[stretch_task],
            habits=[],
            events=[],
            target_date=target_date,
        )
        recovery_result = generator.generate_motivation_and_mantra(
            user_context={"streak_days": 0, "current_scale_level": -2},
            goal_tasks=[recovery_task],
            habits=[],
            events=[],
            target_date=target_date,
        )

        stretch_data = stretch_result["data"]
        recovery_data = recovery_result["data"]

        self.assertIn("deadline is close", stretch_data["motivation"].lower())
        self.assertIn("stretch", stretch_data["motivation"].lower())
        self.assertIn("push the stretch task", stretch_data["mantra"].lower())
        self.assertIn("reset day", recovery_data["motivation"].lower())
        self.assertIn("pace it cleanly", recovery_data["mantra"].lower())


class RoutineProgressEndpointTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="routine-progress@test.com",
            password="Password@123",
        )
        self.client.force_authenticate(self.user)

        today = timezone.localdate()
        self.goal = Goal.objects.create(
            user=self.user,
            title="Progress Goal",
            description="Progress endpoint test data",
            primary_category="career",
            status="in_progress",
            target_date=today + timedelta(days=20),
        )
        milestone = Milestone.objects.create(
            goal=self.goal,
            title="Progress Milestone",
            display_order=1,
            status="in_progress",
        )
        subgoal = SubGoal.objects.create(
            milestone=milestone,
            title="Progress Subgoal",
            display_order=1,
            status="in_progress",
        )
        task = Task.objects.create(
            subgoal=subgoal,
            title="Progress Task",
            status="pending",
            priority="medium",
            estimated_duration_minutes=45,
            display_order=1,
        )
        task_list = DailyTaskList.objects.create(user=self.user, date=today)
        DailyTaskItem.objects.create(
            task_list=task_list,
            item_type="goal_task",
            goal_task=task,
            related_goal=self.goal,
            title=task.title,
            description=task.description,
            priority=task.priority,
            estimated_minutes=task.estimated_duration_minutes,
            display_order=0,
        )
        task_list.update_progress()

    def test_progress_endpoint_rejects_invalid_date(self):
        response = self.client.get("/routines/progress/?date=2026/03/04")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "Invalid date format. Use YYYY-MM-DD.")

    def test_progress_endpoint_returns_expected_payload_shape(self):
        response = self.client.get("/routines/progress/?period=month")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["timePeriod"], "month")
        self.assertIn("overallStats", response.data)
        self.assertIn("habitStats", response.data)
        self.assertIn("categoryStats", response.data)
        self.assertIn("weeklyData", response.data)
        self.assertIn("milestones", response.data)
        self.assertIn("activityHeatmap", response.data)
        self.assertIn("todayTaskSheet", response.data)
        self.assertIn("frictionAudit", response.data)
        self.assertIn("dominant_reason", response.data["frictionAudit"])
        self.assertIn("crossGoalConflicts", response.data)
        self.assertIn("summary", response.data["crossGoalConflicts"])
        self.assertIn("conflicts", response.data["crossGoalConflicts"])
        self.assertIn("feasibilitySuggestions", response.data["crossGoalConflicts"])
        self.assertIn("customIntervalStreak", response.data)
        self.assertIn("customIntervalCurrentStreak", response.data["overallStats"])
        self.assertIn("streakIntervalDays", response.data["overallStats"])

    def test_progress_endpoint_detects_cross_goal_conflicts(self):
        today = timezone.localdate()

        second_goal = Goal.objects.create(
            user=self.user,
            title="Second Goal",
            description="Cross-goal conflict scenario",
            primary_category="financial",
            status="in_progress",
            priority="high",
            target_date=today + timedelta(days=45),
        )
        second_milestone = Milestone.objects.create(
            goal=second_goal,
            title="Second Milestone",
            display_order=1,
            status="in_progress",
        )
        second_subgoal = SubGoal.objects.create(
            milestone=second_milestone,
            title="Second Subgoal",
            display_order=1,
            status="in_progress",
        )
        second_task = Task.objects.create(
            subgoal=second_subgoal,
            title="High-focus finance task",
            status="pending",
            priority="high",
            estimated_duration_minutes=210,
            preferred_time_slot="morning",
            display_order=1,
        )

        task_list = DailyTaskList.objects.get(user=self.user, date=today)
        # Update existing item to create overlap + energy conflict conditions.
        first_item = task_list.tasks.filter(item_type="goal_task").first()
        first_item.priority = "high"
        first_item.time_slot = "morning"
        first_item.estimated_minutes = 220
        first_item.save(update_fields=["priority", "time_slot", "estimated_minutes", "updated_at"])

        DailyTaskItem.objects.create(
            task_list=task_list,
            item_type="goal_task",
            goal_task=second_task,
            related_goal=second_goal,
            title=second_task.title,
            description=second_task.description,
            priority=second_task.priority,
            estimated_minutes=second_task.estimated_duration_minutes,
            time_slot="morning",
            display_order=1,
        )
        task_list.update_progress()

        response = self.client.get("/routines/progress/?period=week")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        conflict_payload = response.data["crossGoalConflicts"]
        summary = conflict_payload["summary"]
        self.assertTrue(summary["has_conflict"])
        self.assertGreaterEqual(summary["total_conflicts"], 2)
        conflict_types = {entry["type"] for entry in conflict_payload["conflicts"]}
        self.assertIn("overload", conflict_types)
        self.assertIn("time_overlap", conflict_types)
        self.assertTrue(len(conflict_payload["feasibilitySuggestions"]) > 0)

    def test_week_overview_endpoint_returns_seven_days(self):
        response = self.client.get("/routines/week/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("week_start", response.data)
        self.assertEqual(len(response.data["days"]), 7)

    def test_streak_endpoint_returns_streak_payload(self):
        response = self.client.get("/routines/streak/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("streak", response.data)
        self.assertIn("customIntervalStreak", response.data)
        self.assertEqual(response.data["streak"]["current_streak_days"], 0)

    def test_streak_endpoint_supports_custom_interval_days(self):
        today = timezone.localdate()
        task_list = DailyTaskList.objects.get(user=self.user, date=today)
        task_list.status = "completed"
        task_list.total_tasks = 1
        task_list.completed_tasks = 1
        task_list.completion_percentage = 100
        task_list.is_fully_completed = True
        task_list.save(
            update_fields=[
                "status",
                "total_tasks",
                "completed_tasks",
                "completion_percentage",
                "is_fully_completed",
                "updated_at",
            ]
        )

        for days_back in (3, 6):
            DailyTaskList.objects.create(
                user=self.user,
                date=today - timedelta(days=days_back),
                status="completed",
                total_tasks=1,
                completed_tasks=1,
                completion_percentage=100,
                is_fully_completed=True,
            )

        response = self.client.get("/routines/streak/?interval_days=3")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["customIntervalStreak"]["interval_days"], 3)
        self.assertGreaterEqual(
            response.data["customIntervalStreak"]["current_streak_intervals"],
            3,
        )

        progress_response = self.client.get("/routines/progress/?period=week&streak_interval_days=3")
        self.assertEqual(progress_response.status_code, status.HTTP_200_OK)
        self.assertEqual(progress_response.data["overallStats"]["streakIntervalDays"], 3)
        self.assertEqual(progress_response.data["customIntervalStreak"]["interval_days"], 3)


class RoutineDeleteEndpointTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="routine-delete-owner@test.com",
            password="Password@123",
        )
        self.other_user = CustomUser.objects.create_user(
            email="routine-delete-other@test.com",
            password="Password@123",
        )
        self.client.force_authenticate(self.user)

        self.owner_routine = DailyTaskList.objects.create(
            user=self.user,
            date=timezone.localdate(),
        )
        self.other_routine = DailyTaskList.objects.create(
            user=self.other_user,
            date=timezone.localdate(),
        )

    def test_owner_can_delete_own_routine(self):
        response = self.client.delete(f"/routines/{self.owner_routine.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(DailyTaskList.objects.filter(id=self.owner_routine.id).exists())

    def test_non_owner_delete_returns_403(self):
        response = self.client.delete(f"/routines/{self.other_routine.id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(DailyTaskList.objects.filter(id=self.other_routine.id).exists())

    def test_delete_missing_routine_returns_404(self):
        DailyTaskList.objects.filter(id=self.owner_routine.id).delete()
        response = self.client.delete(f"/routines/{self.owner_routine.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class RoutineEventConstraintIntegrationTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="routine-events@test.com",
            password="Password@123",
        )

    def _create_goal_task(self, *, title: str, preferred_time_slot: str = "afternoon", estimated_minutes: int = 60):
        goal = Goal.objects.create(
            user=self.user,
            title=f"{title} Goal",
            description="Goal for event integration tests",
            primary_category="career",
            priority="high",
            target_date=timezone.localdate() + timedelta(days=30),
            status="in_progress",
        )
        milestone = Milestone.objects.create(
            goal=goal,
            title=f"{title} Milestone",
            display_order=1,
            priority="high",
            status="in_progress",
        )
        subgoal = SubGoal.objects.create(
            milestone=milestone,
            title=f"{title} Subgoal",
            display_order=1,
            priority="high",
            status="in_progress",
        )
        Task.objects.create(
            subgoal=subgoal,
            title=title,
            status="pending",
            priority="high",
            preferred_time_slot=preferred_time_slot,
            estimated_duration_minutes=estimated_minutes,
            display_order=1,
        )

    def test_recurring_office_event_injects_constraints_metadata(self):
        target_date = date(2026, 3, 10)  # Tuesday
        self._create_goal_task(title="Deep Work Task", preferred_time_slot="afternoon")
        HabitTracker.objects.create(
            user=self.user,
            name="Morning Journal",
            frequency="daily",
            is_active=True,
            estimated_minutes=20,
            priority="medium",
        )
        Event.objects.create(
            user=self.user,
            title="Office Hours",
            description="Mon-Fri office",
            event_type="recurring",
            start_at=datetime.fromisoformat("2026-03-09T09:00:00+05:45"),
            end_at=datetime.fromisoformat("2026-03-09T17:00:00+05:45"),
            is_all_day=False,
            timezone="Asia/Katmandu",
            recurrence={
                "frequency": "weekly",
                "interval": 1,
                "by_weekday": ["MON", "TUE", "WED", "THU", "FRI"],
                "until_date": "2026-12-31",
                "count": None,
            },
            routine_constraint={
                "constraint_mode": "hard",
                "buffer_before_minutes": 15,
                "buffer_after_minutes": 15,
                "routine_policy": "block",
            },
        )

        task_list, created = get_or_create_today_task_list(self.user, target_date)
        self.assertTrue(created)
        constraints = task_list.schedule_constraints
        self.assertEqual(constraints["timezone"], "Asia/Katmandu")
        self.assertGreaterEqual(len(constraints["occupied_windows"]), 1)
        self.assertIn(constraints["fit_summary"]["fit_status"], {"fit", "partial_fit"})
        event_item = task_list.tasks.filter(item_type="event").first()
        self.assertIsNotNone(event_item)
        self.assertEqual(event_item.time_slot, "afternoon")
        first_item = task_list.tasks.order_by("display_order").first()
        self.assertIsNotNone(first_item)
        self.assertEqual(first_item.item_type, "event")

    def test_ad_hoc_meeting_shifts_tasks_out_of_blocked_slot(self):
        target_date = date(2026, 3, 14)
        self._create_goal_task(title="Meeting Day Task", preferred_time_slot="afternoon")
        Event.objects.create(
            user=self.user,
            title="Ad-hoc Meeting",
            description="Blocks full afternoon",
            event_type="one_time",
            start_at=datetime.fromisoformat("2026-03-14T12:00:00+05:45"),
            end_at=datetime.fromisoformat("2026-03-14T18:00:00+05:45"),
            is_all_day=False,
            timezone="Asia/Katmandu",
            recurrence=None,
            routine_constraint={
                "constraint_mode": "hard",
                "buffer_before_minutes": 0,
                "buffer_after_minutes": 0,
                "routine_policy": "shift",
            },
        )

        task_list, _ = get_or_create_today_task_list(self.user, target_date)
        goal_item = task_list.tasks.filter(item_type="goal_task").first()
        self.assertIsNotNone(goal_item)
        self.assertNotEqual(goal_item.time_slot, "afternoon")
        self.assertEqual(task_list.schedule_constraints["fit_summary"]["fallback_strategy"], "none")

    def test_slot_capacity_reservation_distributes_items_across_free_windows(self):
        target_date = date(2026, 3, 17)
        self._create_goal_task(
            title="Capacity Task One",
            preferred_time_slot="morning",
            estimated_minutes=200,
        )
        self._create_goal_task(
            title="Capacity Task Two",
            preferred_time_slot="morning",
            estimated_minutes=200,
        )
        HabitTracker.objects.create(
            user=self.user,
            name="Morning Stretch",
            frequency="daily",
            is_active=True,
            estimated_minutes=180,
            priority="medium",
        )
        Event.objects.create(
            user=self.user,
            title="Morning Blocker",
            description="Blocks first half of morning slot",
            event_type="one_time",
            start_at=datetime.fromisoformat("2026-03-17T06:00:00+05:45"),
            end_at=datetime.fromisoformat("2026-03-17T09:00:00+05:45"),
            is_all_day=False,
            timezone="Asia/Katmandu",
            recurrence=None,
            routine_constraint={
                "constraint_mode": "hard",
                "buffer_before_minutes": 0,
                "buffer_after_minutes": 0,
                "routine_policy": "shift",
            },
        )

        task_list, _ = get_or_create_today_task_list(self.user, target_date)
        self.assertEqual(task_list.schedule_constraints["fit_summary"]["fallback_strategy"], "none")

        habit_item = task_list.tasks.filter(item_type="habit").first()
        self.assertIsNotNone(habit_item)
        self.assertEqual(habit_item.time_slot, "morning")

        goal_slots = set(
            task_list.tasks.filter(item_type="goal_task")
            .values_list("time_slot", flat=True)
        )
        self.assertEqual(goal_slots, {"afternoon", "evening"})

    def test_multi_day_travel_forces_partial_strategy(self):
        target_date = date(2026, 4, 11)
        self._create_goal_task(title="Travel Task", preferred_time_slot="morning")
        HabitTracker.objects.create(
            user=self.user,
            name="Travel Habit",
            frequency="daily",
            is_active=True,
            estimated_minutes=30,
            priority="medium",
        )
        Event.objects.create(
            user=self.user,
            title="Travel",
            description="Multi-day full coverage",
            event_type="multi_day",
            start_at=datetime.fromisoformat("2026-04-10T00:00:00+05:45"),
            end_at=datetime.fromisoformat("2026-04-13T23:59:00+05:45"),
            is_all_day=True,
            timezone="Asia/Katmandu",
            recurrence=None,
            routine_constraint={
                "constraint_mode": "hard",
                "buffer_before_minutes": 0,
                "buffer_after_minutes": 0,
                "routine_policy": "reduce_load",
            },
        )

        task_list, _ = get_or_create_today_task_list(self.user, target_date)
        self.assertEqual(task_list.tasks.exclude(item_type__in=["event", "journal"]).count(), 0)
        self.assertGreaterEqual(task_list.tasks.filter(item_type="event").count(), 1)
        self.assertIsNotNone(task_list.tasks.filter(item_type="journal").first())
        self.assertEqual(task_list.schedule_constraints["fit_summary"]["fallback_strategy"], "partial")
        self.assertEqual(task_list.schedule_constraints["fit_summary"]["fit_status"], "partial_fit")


class HabitTrackerMotivationFieldsTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="habit-motivation@test.com",
            password="Password@123",
        )
        self.client.force_authenticate(self.user)
        self.goal = Goal.objects.create(
            user=self.user,
            title="Breathing Goal",
            description="Improve breathing capacity",
            primary_category="health",
            status="in_progress",
            target_date=timezone.localdate() + timedelta(days=30),
        )

    def test_habit_endpoints_serialize_new_fields_with_safe_defaults(self):
        habit = HabitTracker.objects.create(
            user=self.user,
            name="Morning Breathwork",
            frequency="daily",
            linked_goal=self.goal,
        )

        list_response = self.client.get("/routines/habits/")
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        serialized_habit = list_response.data["habits"][0]

        self.assertEqual(serialized_habit["category"], "other")
        self.assertEqual(serialized_habit["reason_headline"], "")
        self.assertEqual(serialized_habit["reason_body"], "")
        self.assertEqual(serialized_habit["science_badge"], "")
        self.assertEqual(serialized_habit["rewards"], [])
        self.assertEqual(serialized_habit["proof_metric_name"], "")
        self.assertFalse(serialized_habit["ai_suggested"])
        self.assertIsNone(serialized_habit["suggested_time"])
        self.assertIsNone(serialized_habit["time_slot"])
        self.assertFalse(serialized_habit["is_system"])
        self.assertTrue(serialized_habit["is_deletable"])
        self.assertIsNone(serialized_habit["current_proof"])

        detail_response = self.client.get(f"/routines/habits/{habit.id}/")
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        detail_payload = detail_response.data["habit"]
        self.assertEqual(detail_payload["category"], "other")
        self.assertEqual(detail_payload["rewards"], [])
        self.assertIsNone(detail_payload["time_slot"])
        self.assertFalse(detail_payload["is_system"])
        self.assertTrue(detail_payload["is_deletable"])
        self.assertIsNone(detail_payload["current_proof"])

    def test_serializer_ignores_read_only_system_flags_on_create(self):
        response = self.client.post(
            "/routines/habits/",
            data={
                "name": "User Habit",
                "frequency": "daily",
                "is_system": True,
                "is_deletable": False,
                "time_slot": "morning",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        habit = HabitTracker.objects.get(id=response.data["id"])
        self.assertFalse(habit.is_system)
        self.assertTrue(habit.is_deletable)
        self.assertEqual(habit.time_slot, "morning")

    def test_get_current_proof_returns_none_when_not_configured(self):
        habit = HabitTracker.objects.create(
            user=self.user,
            name="Hydration Habit",
            frequency="daily",
        )

        self.assertIsNone(habit.get_current_proof())

    @patch("routine.models.apps.get_model")
    def test_get_current_proof_returns_metric_payload_when_entries_exist(self, mock_get_model):
        habit = HabitTracker.objects.create(
            user=self.user,
            name="Breath Hold Practice",
            frequency="daily",
            linked_goal=self.goal,
            proof_metric_name="Lung Capacity",
        )

        first_entry = SimpleNamespace(metric_value=42.0)
        latest_entry = SimpleNamespace(
            metric_value=61.0,
            metric_target=85.0,
            metric_unit="%",
            metric_direction="up",
            progress_percentage=43,
        )

        queryset = mock_get_model.return_value.objects.filter.return_value.order_by.return_value
        queryset.exists.return_value = True
        queryset.first.return_value = first_entry
        queryset.last.return_value = latest_entry
        queryset.count.return_value = 8

        proof = habit.get_current_proof()

        self.assertEqual(proof, {
            "metric_name": "Lung Capacity",
            "start_value": 42.0,
            "current_value": 61.0,
            "target_value": 85.0,
            "unit": "%",
            "direction": "up",
            "progress_pct": 43,
            "days_tracked": 8,
        })


class SystemHabitsServiceTests(APITestCase):
    def test_seed_service_is_idempotent(self):
        user = CustomUser.objects.create_user(
            email="seed-service@test.com",
            password="Password@123",
        )
        HabitTracker.objects.filter(user=user, is_system=True).delete()

        first_count = seed_system_habits_for_user(user)
        second_count = seed_system_habits_for_user(user)

        self.assertEqual(first_count, 7)
        self.assertEqual(second_count, 0)
        self.assertEqual(HabitTracker.objects.filter(user=user, is_system=True).count(), 7)

    def test_seed_service_creates_non_empty_guidance_for_new_system_habits(self):
        user = CustomUser.objects.create_user(
            email="seed-guidance@test.com",
            password="Password@123",
        )
        HabitTracker.objects.filter(user=user, is_system=True).delete()

        seed_system_habits_for_user(user)

        system_habits = HabitTracker.objects.filter(user=user, is_system=True)
        self.assertEqual(system_habits.count(), 7)
        self.assertFalse(system_habits.filter(description="").exists())
        self.assertFalse(system_habits.filter(reason_body="").exists())

    def test_seed_service_backfills_blank_guidance_without_overwriting_customized_fields(self):
        user = CustomUser.objects.create_user(
            email="seed-backfill@test.com",
            password="Password@123",
        )
        habit = HabitTracker.objects.get(
            user=user,
            name="Visualization",
            is_system=True,
        )
        HabitTracker.objects.filter(pk=habit.pk).update(
            description="",
            reason_body="",
            why_important="",
            estimated_minutes=17,
            time_slot="evening",
            suggested_time=datetime.strptime("20:45:00", "%H:%M:%S").time(),
            is_active=False,
        )

        created_count = seed_system_habits_for_user(user)
        habit.refresh_from_db()

        self.assertEqual(created_count, 0)
        self.assertTrue(habit.description)
        self.assertTrue(habit.reason_body)
        self.assertTrue(habit.why_important)
        self.assertEqual(habit.estimated_minutes, 17)
        self.assertEqual(habit.time_slot, "evening")
        self.assertEqual(str(habit.suggested_time), "20:45:00")
        self.assertFalse(habit.is_active)

    def test_seed_service_does_not_override_non_blank_existing_guidance(self):
        user = CustomUser.objects.create_user(
            email="seed-preserve@test.com",
            password="Password@123",
        )
        habit = HabitTracker.objects.get(
            user=user,
            name="Gratitude Practice",
            is_system=True,
        )
        HabitTracker.objects.filter(pk=habit.pk).update(
            description="Custom guidance stays.",
            reason_body="Custom body stays.",
        )

        seed_system_habits_for_user(user)
        habit.refresh_from_db()

        self.assertEqual(habit.description, "Custom guidance stays.")
        self.assertEqual(habit.reason_body, "Custom body stays.")

    def test_management_command_backfills_missing_system_habits_only(self):
        user = CustomUser.objects.create_user(
            email="seed-command@test.com",
            password="Password@123",
        )
        missing_habit = HabitTracker.objects.filter(user=user, is_system=True).first()
        HabitTracker.objects.filter(pk=missing_habit.pk).delete()

        output = StringIO()
        call_command("seed_system_habits", stdout=output)

        self.assertEqual(HabitTracker.objects.filter(user=user, is_system=True).count(), 7)
        self.assertIn("Seeded 1 habits for user", output.getvalue())

    @patch("authentication.signals.seed_system_habits_for_user", side_effect=RuntimeError("boom"))
    def test_user_creation_does_not_fail_when_seed_raises(self, mock_seed):
        with self.assertLogs("authentication.signals", level="ERROR") as captured:
            user = CustomUser.objects.create_user(
                email="seed-failure@test.com",
                password="Password@123",
            )

        self.assertTrue(Profile.objects.filter(user=user).exists())
        self.assertEqual(HabitTracker.objects.filter(user=user, is_system=True).count(), 0)
        self.assertIn("Failed to seed system habits for user", "\n".join(captured.output))
        mock_seed.assert_called_once()


class SystemHabitDetailApiTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="system-habit-detail@test.com",
            password="Password@123",
        )
        self.client.force_authenticate(self.user)
        self.system_habit = HabitTracker.objects.create(
            user=self.user,
            name="Protected System Habit",
            frequency="daily",
            is_system=True,
            is_deletable=False,
            estimated_minutes=10,
            time_slot="morning",
            suggested_time=datetime.strptime("06:00:00", "%H:%M:%S").time(),
        )
        self.user_habit = HabitTracker.objects.create(
            user=self.user,
            name="Editable Habit",
            frequency="daily",
            estimated_minutes=20,
        )

    def test_system_habit_delete_is_forbidden(self):
        response = self.client.delete(f"/routines/habits/{self.system_habit.id}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(HabitTracker.objects.filter(id=self.system_habit.id).exists())

    def test_system_habit_put_is_forbidden(self):
        response = self.client.put(
            f"/routines/habits/{self.system_habit.id}/",
            data={"name": "Renamed"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.system_habit.refresh_from_db()
        self.assertEqual(self.system_habit.name, "Protected System Habit")

    def test_system_habit_patch_allows_only_safe_fields(self):
        response = self.client.patch(
            f"/routines/habits/{self.system_habit.id}/",
            data={
                "estimated_minutes": 25,
                "time_slot": "evening",
                "suggested_time": "20:30:00",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.system_habit.refresh_from_db()
        self.assertEqual(self.system_habit.estimated_minutes, 25)
        self.assertEqual(self.system_habit.time_slot, "evening")
        self.assertEqual(str(self.system_habit.suggested_time), "20:30:00")

    def test_system_habit_patch_rejects_disallowed_fields(self):
        response = self.client.patch(
            f"/routines/habits/{self.system_habit.id}/",
            data={"name": "Blocked Rename", "estimated_minutes": 12},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["disallowed_fields"], ["name"])
        self.system_habit.refresh_from_db()
        self.assertEqual(self.system_habit.name, "Protected System Habit")

    def test_habit_list_backfills_blank_system_guidance(self):
        habit = HabitTracker.objects.get(
            user=self.user,
            name="Visualization",
            is_system=True,
        )
        HabitTracker.objects.filter(pk=habit.pk).update(description="", reason_body="")

        response = self.client.get("/routines/habits/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = next(item for item in response.data["habits"] if item["name"] == "Visualization")
        self.assertTrue(payload["description"])
        self.assertTrue(payload["reason_body"])

    def test_habit_detail_backfills_blank_reason_body_for_system_habit(self):
        habit = HabitTracker.objects.get(
            user=self.user,
            name="Gratitude Practice",
            is_system=True,
        )
        HabitTracker.objects.filter(pk=habit.pk).update(reason_body="")

        response = self.client.get(f"/routines/habits/{habit.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["habit"]["reason_body"])

    def test_non_system_habit_keeps_existing_put_patch_and_delete_behavior(self):
        patch_response = self.client.patch(
            f"/routines/habits/{self.user_habit.id}/",
            data={"name": "Partially Updated"},
            format="json",
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)

        put_response = self.client.put(
            f"/routines/habits/{self.user_habit.id}/",
            data={"name": "Fully Updated"},
            format="json",
        )
        self.assertEqual(put_response.status_code, status.HTTP_200_OK)

        delete_response = self.client.delete(f"/routines/habits/{self.user_habit.id}/")
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(HabitTracker.objects.filter(id=self.user_habit.id).exists())


class HealthProfileEndpointTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="health-profile@test.com",
            password="Password@123",
        )
        self.url = "/routines/health-profile/"

    def test_unauthenticated_access_returns_401(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_before_profile_exists_returns_404(self):
        self.client.force_authenticate(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_post_creates_profile_and_returns_201(self):
        self.client.force_authenticate(self.user)
        payload = {
            "bad_habits": ["smoking"],
            "conditions": ["asthma"],
            "on_medication": True,
            "budget_level": "low",
            "willpower_level": "medium",
            "stress_level": "moderate",
            "fitness_level": "light",
            "commitment_words": "I choose my health every day",
        }
        response = self.client.post(self.url, data=payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["health_profile"]["bad_habits"], ["smoking"])
        self.assertTrue(HealthProfile.objects.filter(user=self.user).exists())

    def test_post_allows_multiple_profiles_per_user(self):
        self.client.force_authenticate(self.user)
        HealthProfile.objects.create(user=self.user, bad_habits=["sleeping_late"])
        response = self.client.post(self.url, data={"bad_habits": ["smoking"]}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(HealthProfile.objects.filter(user=self.user).count(), 2)
        self.assertEqual(HealthProfile.objects.filter(user=self.user, is_active=True).count(), 1)

    def test_new_profile_becomes_active_and_deactivates_previous_profile(self):
        self.client.force_authenticate(self.user)
        original = HealthProfile.objects.create(user=self.user, bad_habits=["sleeping_late"])
        response = self.client.post(self.url, data={"bad_habits": ["smoking"]}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        original.refresh_from_db()
        new_profile = HealthProfile.objects.get(id=response.data["health_profile"]["id"])
        self.assertFalse(original.is_active)
        self.assertTrue(new_profile.is_active)

    def test_patch_updates_only_supplied_fields(self):
        self.client.force_authenticate(self.user)
        profile = HealthProfile.objects.create(
            user=self.user,
            bad_habits=["smoking"],
            stress_level="high",
            commitment_words="Original words",
        )
        response = self.client.patch(
            self.url,
            data={"stress_level": "low"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        profile.refresh_from_db()
        self.assertEqual(profile.stress_level, "low")
        self.assertEqual(profile.bad_habits, ["smoking"])
        self.assertEqual(profile.commitment_words, "Original words")

    def test_collection_patch_rejects_ambiguity_when_multiple_profiles_exist(self):
        self.client.force_authenticate(self.user)
        HealthProfile.objects.create(user=self.user, bad_habits=["smoking"])
        HealthProfile.objects.create(user=self.user, bad_habits=["junk_food"])
        response = self.client.patch(self.url, data={"stress_level": "low"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Multiple health profiles exist", response.data["error"])

    def test_job_type_other_roundtrip(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            self.url,
            data={
                "bad_habits": ["smoking"],
                "conditions": ["none"],
                "job_type": "other",
                "job_type_other": "Delivery rider",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["health_profile"]["job_type"], "other")
        self.assertEqual(response.data["health_profile"]["job_type_other"], "Delivery rider")

        patch_response = self.client.patch(
            self.url,
            data={"job_type_other": "Marine engineer"},
            format="json",
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_response.data["health_profile"]["job_type_other"], "Marine engineer")

    def test_get_returns_full_profile_after_creation(self):
        self.client.force_authenticate(self.user)
        HealthProfile.objects.create(
            user=self.user,
            bad_habits=["smoking", "sleeping_late"],
            conditions=["anxiety"],
            on_medication=False,
            commitment_person="My daughter",
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        profile_payload = response.data["health_profile"]
        self.assertEqual(profile_payload["bad_habits"], ["smoking", "sleeping_late"])
        self.assertEqual(profile_payload["conditions"], ["anxiety"])
        self.assertEqual(profile_payload["commitment_person"], "My daughter")

    def test_detail_patch_can_activate_specific_profile(self):
        self.client.force_authenticate(self.user)
        active_profile = HealthProfile.objects.create(user=self.user, bad_habits=["sleeping_late"])
        inactive_profile = HealthProfile.objects.create(user=self.user, bad_habits=["smoking"])
        response = self.client.patch(
            f"/routines/health-profile/{active_profile.id}/",
            data={"is_active": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response = self.client.patch(
            f"/routines/health-profile/{inactive_profile.id}/",
            data={"is_active": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        active_profile.refresh_from_db()
        inactive_profile.refresh_from_db()
        self.assertFalse(active_profile.is_active)
        self.assertTrue(inactive_profile.is_active)


class HabitRecommendationServiceTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="habit-service@test.com",
            password="Password@123",
        )
        HealthProfile.objects.create(
            user=self.user,
            bad_habits=["smoking"],
            conditions=["asthma"],
            job_type="desk",
            sleep_pattern="irregular",
            budget_level="low",
            willpower_level="medium",
            stress_level="high",
            motivation_style="progress",
        )

    def test_build_prompt_mentions_all_required_sections(self):
        profile = HealthProfile.objects.filter(user=self.user).first()
        prompt = _build_habit_prompt(profile.as_ai_context(), goal=None)
        self.assertIn("habits_to_break", prompt)
        self.assertIn("health_conditions", prompt)
        self.assertIn("lifestyle", prompt)
        self.assertIn("psychology", prompt)
        self.assertIn("Analyze and combine", prompt)
        self.assertIn("reason_body", prompt)
        self.assertIn("practical execution steps", prompt)

    def test_normalize_ai_habit_converts_reason_body_steps_list_to_numbered_text(self):
        normalized = _normalize_ai_habit(
            {
                "name": "Morning breath reset",
                "category": "breathing",
                "estimated_minutes": 10,
                "frequency": "daily",
                "reason_headline": "Calm your mind first thing",
                "reason_body": [
                    "Sit upright and relax shoulders.",
                    "Inhale slowly for 4 seconds.",
                    "Exhale for 6 seconds and repeat for 10 minutes.",
                ],
            }
        )

        self.assertIsNotNone(normalized)
        self.assertEqual(
            normalized["reason_body"],
            "1. Sit upright and relax shoulders.\n"
            "2. Inhale slowly for 4 seconds.\n"
            "3. Exhale for 6 seconds and repeat for 10 minutes.",
        )

    @patch("routine.habit_recommendation_service.ResponseParser")
    @patch("routine.habit_recommendation_service.create_routed_provider")
    def test_generation_skips_pending_duplicates(self, mock_provider_factory, mock_parser_cls):
        from routine.models import HabitRecommendation

        HabitRecommendation.objects.create(
            user=self.user,
            name="Box breathing",
            icon="*",
            category="breathing",
            estimated_minutes=10,
            frequency="daily",
            status="pending",
        )

        mock_provider = mock_provider_factory.return_value
        mock_provider.generate_response.return_value = SimpleNamespace(content="{}")

        mock_parser = mock_parser_cls.return_value
        mock_parser.parse_json.return_value = {
            "habits": [
                {
                    "name": "Box breathing",
                    "category": "breathing",
                    "estimated_minutes": 10,
                    "frequency": "daily",
                },
                {
                    "name": "Turmeric milk",
                    "category": "nutrition",
                    "estimated_minutes": 5,
                    "frequency": "daily",
                },
            ]
        }

        generated = generate_habit_recommendations_for_user(self.user)
        self.assertEqual(len(generated), 1)
        self.assertEqual(generated[0].name, "Turmeric milk")
        self.assertEqual(
            HabitRecommendation.objects.filter(user=self.user, status="pending").count(),
            2,
        )

    @patch("routine.habit_recommendation_service.ResponseParser")
    @patch("routine.habit_recommendation_service.create_routed_provider")
    def test_generation_uses_active_profile_when_profile_id_is_omitted(self, mock_provider_factory, mock_parser_cls):
        active_profile = HealthProfile.objects.create(
            user=self.user,
            bad_habits=["junk_food"],
            is_active=True,
        )
        old_profile = HealthProfile.objects.filter(user=self.user).exclude(id=active_profile.id).first()
        old_profile.is_active = False
        old_profile.save(update_fields=["is_active", "updated_at"])

        mock_provider = mock_provider_factory.return_value
        mock_provider.generate_response.return_value = SimpleNamespace(content="{}")
        mock_parser = mock_parser_cls.return_value
        mock_parser.parse_json.return_value = {
            "habits": [
                {
                    "name": "Box breathing",
                    "category": "breathing",
                    "estimated_minutes": 10,
                    "frequency": "daily",
                }
            ]
        }

        generated = generate_habit_recommendations_for_user(self.user)
        self.assertEqual(len(generated), 1)
        self.assertEqual(generated[0].source_health_profile_id, active_profile.id)


class HabitRecommendationEndpointTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="habit-suggestions@test.com",
            password="Password@123",
        )
        self.other_user = CustomUser.objects.create_user(
            email="habit-suggestions-other@test.com",
            password="Password@123",
        )
        self.client.force_authenticate(self.user)
        self.goal = Goal.objects.create(
            user=self.user,
            title="Improve cardio",
            description="Cardio consistency",
            primary_category="health",
            status="in_progress",
            target_date=timezone.localdate() + timedelta(days=90),
        )
        self.suggest_url = "/routines/habits/suggest/"
        self.list_url = "/routines/habits/suggestions/"
        self.profile_a = HealthProfile.objects.create(user=self.user, bad_habits=["smoking"])
        self.profile_b = HealthProfile.objects.create(user=self.user, bad_habits=["junk_food"])

    def _create_recommendation(self, **overrides):
        defaults = {
            "user": self.user,
            "suggested_for_goal": self.goal,
            "source_health_profile": self.profile_a,
            "name": "Brisk walk",
            "icon": "🚶",
            "category": "movement",
            "estimated_minutes": 15,
            "frequency": "daily",
            "status": "pending",
        }
        defaults.update(overrides)
        from routine.models import HabitRecommendation
        return HabitRecommendation.objects.create(**defaults)

    def test_suggest_without_health_profile_returns_400(self):
        HealthProfile.objects.filter(user=self.user).delete()
        response = self.client.post(self.suggest_url, data={"goal_id": str(self.goal.id)}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "Complete your health profile first.")

    @patch("routine.views.generate_habit_recommendations_for_user")
    def test_suggest_creates_pending_recommendations_and_not_habits(self, mock_generate):
        HealthProfile.objects.create(user=self.user, existing_habits=[])

        def _factory(user, goal_id=None, profile_id=None):
            rec1 = self._create_recommendation(name="Morning hydration")
            rec2 = self._create_recommendation(name="Evening breathing")
            return [rec1, rec2]

        mock_generate.side_effect = _factory

        response = self.client.post(self.suggest_url, data={"goal_id": str(self.goal.id)}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(response.data["suggestions"]), 2)

        from routine.models import HabitRecommendation
        self.assertEqual(HabitRecommendation.objects.filter(user=self.user, status="pending").count(), 2)
        self.assertEqual(HabitTracker.objects.filter(user=self.user, ai_suggested=True).count(), 0)

    def test_accept_creates_habit_tracker_and_returns_it(self):
        recommendation = self._create_recommendation(
            name="Box breathing",
            reason_headline="Calm nervous system",
            reason_body="Helps reduce stress load.",
            science_badge="Backed by breathing studies",
            proof_metric_name="Resting Heart Rate",
            rewards=[{"icon": "💨", "label": "Calmer focus", "sub": "feel grounded"}],
        )
        response = self.client.post(f"/routines/habits/suggestions/{recommendation.id}/accept/", data={})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        recommendation.refresh_from_db()
        self.assertEqual(recommendation.status, "accepted")
        self.assertIsNotNone(recommendation.habit_tracker_id)
        self.assertEqual(HabitTracker.objects.filter(user=self.user, name="Box breathing").count(), 1)
        habit = HabitTracker.objects.get(id=recommendation.habit_tracker_id)
        self.assertEqual(habit.description, "Helps reduce stress load.")
        self.assertEqual(habit.why_important, "Calm nervous system")

    def test_accept_is_idempotent(self):
        recommendation = self._create_recommendation(name="Hydration reminder")
        first_response = self.client.post(f"/routines/habits/suggestions/{recommendation.id}/accept/", data={})
        second_response = self.client.post(f"/routines/habits/suggestions/{recommendation.id}/accept/", data={})
        self.assertEqual(first_response.status_code, status.HTTP_200_OK)
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        recommendation.refresh_from_db()
        self.assertEqual(HabitTracker.objects.filter(user=self.user, name="Hydration reminder").count(), 1)
        self.assertEqual(str(first_response.data["habit"]["id"]), str(recommendation.habit_tracker_id))
        self.assertEqual(str(second_response.data["habit"]["id"]), str(recommendation.habit_tracker_id))

    def test_reject_sets_status(self):
        recommendation = self._create_recommendation()
        response = self.client.post(f"/routines/habits/suggestions/{recommendation.id}/reject/", data={})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        recommendation.refresh_from_db()
        self.assertEqual(recommendation.status, "rejected")
        self.assertIsNotNone(recommendation.reviewed_at)

    def test_snooze_sets_status_and_date(self):
        recommendation = self._create_recommendation()
        target_date = timezone.localdate() + timedelta(days=3)
        response = self.client.post(
            f"/routines/habits/suggestions/{recommendation.id}/snooze/",
            data={"until_date": str(target_date)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        recommendation.refresh_from_db()
        self.assertEqual(recommendation.status, "snoozed")
        self.assertEqual(recommendation.snooze_until, target_date)

    def test_list_filters_by_status(self):
        self._create_recommendation(status="pending", name="A")
        self._create_recommendation(status="rejected", name="B")
        response = self.client.get(f"{self.list_url}?status=pending")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["suggestions"]), 1)
        self.assertEqual(response.data["suggestions"][0]["name"], "A")

    def test_list_filters_by_profile_id(self):
        self._create_recommendation(name="A", source_health_profile=self.profile_a)
        self._create_recommendation(name="B", source_health_profile=self.profile_b)
        response = self.client.get(f"{self.list_url}?profile_id={self.profile_b.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["suggestions"]), 1)
        self.assertEqual(response.data["suggestions"][0]["name"], "B")

    def test_cannot_accept_other_users_recommendation(self):
        from routine.models import HabitRecommendation
        recommendation = HabitRecommendation.objects.create(
            user=self.other_user,
            name="Other user habit",
            icon="⭐",
            category="other",
            estimated_minutes=20,
            frequency="daily",
            status="pending",
        )
        response = self.client.post(f"/routines/habits/suggestions/{recommendation.id}/accept/", data={})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class GoalProgressEntryAPITests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="goal-progress@test.com",
            password="Password@123",
        )
        self.other_user = CustomUser.objects.create_user(
            email="goal-progress-other@test.com",
            password="Password@123",
        )
        self.client.force_authenticate(self.user)
        self.goal = Goal.objects.create(
            user=self.user,
            title="Improve VO2 Max",
            description="Track cardio improvements",
            primary_category="health",
            status="in_progress",
            target_date=timezone.localdate() + timedelta(days=90),
        )
        self.other_goal = Goal.objects.create(
            user=self.other_user,
            title="Other goal",
            description="Other user goal",
            primary_category="health",
            status="in_progress",
            target_date=timezone.localdate() + timedelta(days=90),
        )
        self.progress_url = f"/goal/goals/{self.goal.id}/progress/"

    def test_post_creates_entry_and_returns_progress_percentage(self):
        response = self.client.post(
            self.progress_url,
            data={
                "metric_name": "Lung Capacity",
                "metric_value": 61,
                "metric_unit": "%",
                "metric_direction": "up",
                "domain": "physical",
                "metric_start": 38,
                "metric_target": 85,
                "date": str(timezone.localdate()),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["entry"]["progress_percentage"], 48)
        self.assertEqual(GoalProgressEntry.objects.filter(user=self.user).count(), 1)

    def test_post_upserts_existing_entry(self):
        target_date = timezone.localdate()
        GoalProgressEntry.objects.create(
            goal=self.goal,
            user=self.user,
            date=target_date,
            metric_name="Lung Capacity",
            metric_value=50,
            metric_unit="%",
            metric_direction="up",
            domain="physical",
            metric_start=38,
            metric_target=85,
        )

        response = self.client.post(
            self.progress_url,
            data={
                "metric_name": "Lung Capacity",
                "metric_value": 62,
                "metric_unit": "%",
                "metric_direction": "up",
                "domain": "physical",
                "metric_start": 38,
                "metric_target": 85,
                "date": str(target_date),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(GoalProgressEntry.objects.filter(goal=self.goal, date=target_date, metric_name="Lung Capacity").count(), 1)
        entry = GoalProgressEntry.objects.get(goal=self.goal, date=target_date, metric_name="Lung Capacity")
        self.assertEqual(entry.metric_value, 62)

    def test_get_history_returns_entries_in_ascending_date_order(self):
        base_date = timezone.localdate()
        GoalProgressEntry.objects.create(
            goal=self.goal,
            user=self.user,
            date=base_date + timedelta(days=2),
            metric_name="Lung Capacity",
            metric_value=60,
            metric_unit="%",
            metric_direction="up",
            domain="physical",
            metric_start=38,
            metric_target=85,
        )
        GoalProgressEntry.objects.create(
            goal=self.goal,
            user=self.user,
            date=base_date,
            metric_name="Lung Capacity",
            metric_value=50,
            metric_unit="%",
            metric_direction="up",
            domain="physical",
            metric_start=38,
            metric_target=85,
        )

        response = self.client.get(self.progress_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        dates = [entry["date"] for entry in response.data["entries"]]
        self.assertEqual(dates, sorted(dates))

    def test_dashboard_returns_domain_grouping_and_sparkline(self):
        base_date = timezone.localdate() - timedelta(days=8)
        for idx in range(9):
            GoalProgressEntry.objects.create(
                goal=self.goal,
                user=self.user,
                date=base_date + timedelta(days=idx),
                metric_name="Lung Capacity",
                metric_value=40 + idx,
                metric_unit="%",
                metric_direction="up",
                domain="physical",
                metric_start=38,
                metric_target=85,
            )

        response = self.client.get("/routines/progress/dashboard/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        physical_metrics = response.data["dashboard"]["physical"]
        self.assertEqual(len(physical_metrics), 1)
        metric = physical_metrics[0]
        self.assertEqual(metric["goal_id"], str(self.goal.id))
        self.assertEqual(metric["metric_name"], "Lung Capacity")
        self.assertEqual(len(metric["sparkline"]), 7)
        self.assertEqual(response.data["dashboard"]["mental"], [])
        self.assertEqual(response.data["dashboard"]["lifestyle"], [])

    def test_progress_percentage_handles_up_down_and_clamp_edges(self):
        up_entry = GoalProgressEntry(
            goal=self.goal,
            user=self.user,
            date=timezone.localdate(),
            metric_name="Energy",
            metric_value=120,
            metric_unit="pts",
            metric_direction="up",
            domain="mental",
            metric_start=20,
            metric_target=100,
        )
        down_entry = GoalProgressEntry(
            goal=self.goal,
            user=self.user,
            date=timezone.localdate(),
            metric_name="Stress",
            metric_value=45,
            metric_unit="pts",
            metric_direction="down",
            domain="mental",
            metric_start=80,
            metric_target=40,
        )
        equal_entry = GoalProgressEntry(
            goal=self.goal,
            user=self.user,
            date=timezone.localdate(),
            metric_name="Baseline",
            metric_value=10,
            metric_unit="pts",
            metric_direction="up",
            domain="lifestyle",
            metric_start=10,
            metric_target=10,
        )
        negative_entry = GoalProgressEntry(
            goal=self.goal,
            user=self.user,
            date=timezone.localdate(),
            metric_name="Sleep Debt",
            metric_value=120,
            metric_unit="min",
            metric_direction="down",
            domain="lifestyle",
            metric_start=60,
            metric_target=30,
        )

        self.assertEqual(up_entry.progress_percentage, 100)
        self.assertEqual(down_entry.progress_percentage, 87)
        self.assertEqual(equal_entry.progress_percentage, 100)
        self.assertEqual(negative_entry.progress_percentage, 0)

    def test_progress_endpoints_are_owner_scoped(self):
        response = self.client.post(
            f"/goal/goals/{self.other_goal.id}/progress/",
            data={
                "metric_name": "Lung Capacity",
                "metric_value": 60,
                "metric_unit": "%",
                "metric_start": 40,
                "metric_target": 85,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        response = self.client.get(f"/goal/goals/{self.other_goal.id}/progress/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class DailyBriefAPITests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="daily-brief@test.com",
            password="Password@123",
        )
        self.client.force_authenticate(self.user)
        self.today_url = "/routines/brief/today/"
        self.track_status_url = "/routines/brief/track-status/"

    def test_get_generates_deterministic_three_sentence_brief_when_missing(self):
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)

        yesterday_list = DailyTaskList.objects.create(
            user=self.user,
            date=yesterday,
            total_tasks=2,
            completed_tasks=1,
            completion_percentage=50,
            is_fully_completed=False,
            status="in_progress",
        )
        DailyTaskItem.objects.create(
            task_list=yesterday_list,
            item_type="habit",
            title="Hydration",
            description="Drink water",
            priority="medium",
            estimated_minutes=10,
            removed_by_user=False,
            display_order=0,
        )
        goal = Goal.objects.create(
            user=self.user,
            title="Revenue Goal",
            description="Increase recurring revenue",
            primary_category="financial",
            status="in_progress",
            target_date=today + timedelta(days=20),
        )
        GoalProgressEntry.objects.create(
            user=self.user,
            goal=goal,
            date=yesterday,
            metric_name="MRR",
            metric_unit="$",
            metric_value=2500,
            metric_start=1000,
            metric_target=5000,
            metric_direction="up",
        )
        Event.objects.create(
            user=self.user,
            title="Client Call",
            description="Morning sync",
            event_type="one_time",
            start_at=datetime.fromisoformat(f"{today.isoformat()}T10:00:00+00:00"),
            end_at=datetime.fromisoformat(f"{today.isoformat()}T11:00:00+00:00"),
            is_all_day=False,
            timezone="UTC",
            recurrence=None,
        )
        HealthProfile.objects.create(
            user=self.user,
            stress_level="high",
            willpower_level="low",
            sleep_pattern="night_owl",
        )
        DailyBrief.objects.create(
            user=self.user,
            date=yesterday,
            brief_text="Yesterday brief.",
            habit_completion_yesterday=60.0,
            missed_habits_yesterday=[],
            goal_metrics_snapshot={},
            upcoming_events_today=[],
            streak_at_generation=2,
            track_status="behind",
        )

        response = self.client.get(self.today_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(DailyBrief.objects.filter(user=self.user, date=timezone.localdate()).exists())
        self.assertIn("brief", response.data)
        brief_text = response.data["brief"]["brief_text"]
        self.assertEqual(len([part for part in brief_text.rstrip(".").split(". ") if part]), 3)
        self.assertIn("50% completion", brief_text)
        self.assertIn("hydration", brief_text.lower())
        self.assertIn("client call", brief_text.lower())
        self.assertIn("lighter than your ambition", brief_text.lower())

        brief = DailyBrief.objects.get(user=self.user, date=timezone.localdate())
        self.assertEqual(brief.habit_completion_yesterday, 50.0)
        self.assertEqual(brief.missed_habits_yesterday, ["Hydration"])
        self.assertEqual(brief.streak_at_generation, 0)
        self.assertTrue(brief.goal_metrics_snapshot)
        self.assertEqual(len(brief.upcoming_events_today), 1)

    def test_get_returns_cached_brief_on_second_call(self):

        first_response = self.client.get(self.today_url)
        second_response = self.client.get(self.today_url)

        self.assertEqual(first_response.status_code, status.HTTP_200_OK)
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        self.assertEqual(DailyBrief.objects.filter(user=self.user, date=timezone.localdate()).count(), 1)
        self.assertEqual(first_response.data["brief"]["id"], second_response.data["brief"]["id"])

    def test_get_includes_recurring_and_multi_day_events(self):
        today = timezone.localdate()
        Event.objects.create(
            user=self.user,
            title="Recurring Standup",
            description="Daily sync",
            event_type="recurring",
            start_at=datetime.fromisoformat(f"{today.isoformat()}T09:00:00+00:00"),
            end_at=datetime.fromisoformat(f"{today.isoformat()}T09:30:00+00:00"),
            is_all_day=False,
            timezone="UTC",
            recurrence={"frequency": "daily", "interval": 1, "until_date": today.isoformat(), "count": None},
        )
        Event.objects.create(
            user=self.user,
            title="Conference",
            description="Multi-day event",
            event_type="multi_day",
            start_at=datetime.fromisoformat(f"{(today - timedelta(days=1)).isoformat()}T12:00:00+00:00"),
            end_at=datetime.fromisoformat(f"{(today + timedelta(days=1)).isoformat()}T12:00:00+00:00"),
            is_all_day=False,
            timezone="UTC",
            recurrence=None,
        )

        response = self.client.get(self.today_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        event_titles = {item["title"] for item in response.data["brief"]["upcoming_events_today"]}
        self.assertIn("Recurring Standup", event_titles)
        self.assertIn("Conference", event_titles)

    def test_get_reconciles_streak_snapshot_before_brief_creation(self):
        today = timezone.localdate()
        completed_day = today - timedelta(days=2)
        missed_day = today - timedelta(days=1)

        DailyTaskList.objects.create(
            user=self.user,
            date=completed_day,
            total_tasks=1,
            completed_tasks=1,
            completion_percentage=100,
            is_fully_completed=True,
            status="completed",
        )
        DailyTaskList.objects.create(
            user=self.user,
            date=missed_day,
            total_tasks=1,
            completed_tasks=0,
            completion_percentage=0,
            is_fully_completed=False,
            status="pending",
        )
        DisciplineStreak.objects.update_or_create(
            user=self.user,
            defaults={
                "current_streak_days": 6,
                "current_streak_start": completed_day - timedelta(days=5),
                "longest_streak_days": 6,
                "longest_streak_start": completed_day - timedelta(days=5),
                "longest_streak_end": completed_day,
                "total_perfect_days": 6,
                "total_days_tracked": 6,
                "last_tracked_date": completed_day,
            },
        )

        response = self.client.get(self.today_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["brief"]["streak_at_generation"], 0)
        brief = DailyBrief.objects.get(user=self.user, date=today)
        self.assertEqual(brief.streak_at_generation, 0)

    def test_post_track_status_sets_status_and_timestamp(self):
        DailyBrief.objects.create(
            user=self.user,
            date=timezone.localdate(),
            brief_text="Today you continue steadily.",
            habit_completion_yesterday=40.0,
            missed_habits_yesterday=["Hydration"],
            goal_metrics_snapshot={},
            upcoming_events_today=[],
            streak_at_generation=2,
        )

        response = self.client.post(
            self.track_status_url,
            data={"status": "on_track"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        brief = DailyBrief.objects.get(user=self.user, date=timezone.localdate())
        self.assertEqual(brief.track_status, "on_track")
        self.assertIsNotNone(brief.track_status_set_at)

    def test_post_track_status_invalid_value_returns_400(self):
        response = self.client.post(
            self.track_status_url,
            data={"status": "invalid"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("status", response.data)

    def test_unauthenticated_returns_401(self):
        self.client.force_authenticate(user=None)
        today_response = self.client.get(self.today_url)
        track_response = self.client.post(self.track_status_url, data={"status": "on_track"}, format="json")
        self.assertEqual(today_response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(track_response.status_code, status.HTTP_401_UNAUTHORIZED)


class SystemHabitModelGuardTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="system-habit-model@test.com",
            password="Password@123",
        )
        self.system_habit = HabitTracker.objects.create(
            user=self.user,
            name="Protected System Habit",
            frequency="daily",
            estimated_minutes=10,
            is_system=True,
            is_deletable=False,
            suggested_time=datetime.strptime("07:00", "%H:%M").time(),
            time_slot="morning",
        )

    def test_delete_system_habit_is_blocked_at_model_layer(self):
        with self.assertRaises(ValidationError):
            self.system_habit.delete()

    def test_mutating_disallowed_system_habit_field_is_blocked(self):
        self.system_habit.name = "Renamed"
        with self.assertRaises(ValidationError):
            self.system_habit.save()

    def test_mutating_allowed_system_habit_timing_field_succeeds(self):
        self.system_habit.estimated_minutes = 15
        self.system_habit.save(update_fields=["estimated_minutes", "updated_at"])
        self.system_habit.refresh_from_db()
        self.assertEqual(self.system_habit.estimated_minutes, 15)

    def test_record_completion_updates_system_habit_streak_fields(self):
        completion_date = timezone.localdate()
        self.system_habit.record_completion(completion_date)
        self.system_habit.refresh_from_db()

        self.assertEqual(self.system_habit.current_streak, 1)
        self.assertEqual(self.system_habit.longest_streak, 1)
        self.assertEqual(self.system_habit.total_completions, 1)
        self.assertEqual(self.system_habit.last_completed_date, completion_date)


class WakeUpDetectionTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="wake@test.com",
            password="Password@123",
        )
        token = RefreshToken.for_user(self.user).access_token
        self.access_token = str(token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")

    @staticmethod
    def _local_dt_to_utc(local_date: date, hour: int, minute: int, timezone_name: str) -> datetime:
        local = datetime(
            year=local_date.year,
            month=local_date.month,
            day=local_date.day,
            hour=hour,
            minute=minute,
            tzinfo=ZoneInfo(timezone_name),
        )
        return local.astimezone(ZoneInfo("UTC"))

    def _create_interaction(self, *, local_date: date, hour: int, minute: int, timezone_name: str = "UTC"):
        WakeInteraction.objects.create(
            user=self.user,
            local_date=local_date,
            first_interaction_at=self._local_dt_to_utc(local_date, hour, minute, timezone_name),
            timezone_name=timezone_name,
            source_path="/auth/user/",
            source_method="GET",
        )

    def _create_goal_with_tasks_for_schedule_tests(self):
        goal = Goal.objects.create(
            user=self.user,
            title="Wake Baseline Goal",
            description="Wake baseline routine fit",
            primary_category="career",
            priority="high",
            target_date=timezone.localdate() + timedelta(days=30),
            status="in_progress",
        )
        milestone = Milestone.objects.create(
            goal=goal,
            title="Baseline Milestone",
            display_order=1,
            priority="high",
            status="in_progress",
        )
        subgoal = SubGoal.objects.create(
            milestone=milestone,
            title="Baseline Subgoal",
            display_order=1,
            priority="high",
            status="in_progress",
        )
        explicit = Task.objects.create(
            subgoal=subgoal,
            title="Explicit evening task",
            status="pending",
            priority="high",
            preferred_time_slot="evening",
            scheduled_time=datetime.strptime("21:15", "%H:%M").time(),
            estimated_duration_minutes=45,
            display_order=1,
        )
        inferred = Task.objects.create(
            subgoal=subgoal,
            title="Focus block",
            status="pending",
            priority="medium",
            estimated_duration_minutes=45,
            display_order=2,
        )
        return explicit, inferred

    @patch("routine.wake_service.timezone.now")
    def test_first_interaction_logged_once_per_day(self, mock_now):
        first_time = datetime(2026, 3, 6, 1, 0, tzinfo=ZoneInfo("UTC"))
        later_time = datetime(2026, 3, 6, 2, 0, tzinfo=ZoneInfo("UTC"))
        mock_now.return_value = first_time
        response_a = self.client.get("/auth/user/")
        self.assertEqual(response_a.status_code, status.HTTP_200_OK)

        mock_now.return_value = later_time
        response_b = self.client.get("/auth/user/")
        self.assertEqual(response_b.status_code, status.HTTP_200_OK)

        records = WakeInteraction.objects.filter(user=self.user)
        self.assertEqual(records.count(), 1)
        interaction = records.first()
        self.assertEqual(interaction.first_interaction_at, first_time)

    @patch("routine.wake_service.timezone.now")
    def test_timezone_local_date_bucketing_handles_transition(self, mock_now):
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {self.access_token}",
            HTTP_X_USER_TIMEZONE="America/New_York",
        )
        before_midnight_local = datetime(2026, 3, 8, 4, 30, tzinfo=ZoneInfo("UTC"))
        after_midnight_local = datetime(2026, 3, 8, 5, 30, tzinfo=ZoneInfo("UTC"))

        mock_now.return_value = before_midnight_local
        response_a = self.client.get("/auth/user/")
        self.assertEqual(response_a.status_code, status.HTTP_200_OK)

        mock_now.return_value = after_midnight_local
        response_b = self.client.get("/auth/user/")
        self.assertEqual(response_b.status_code, status.HTTP_200_OK)

        local_dates = list(
            WakeInteraction.objects.filter(user=self.user).order_by("local_date").values_list("local_date", flat=True)
        )
        self.assertEqual(local_dates, [date(2026, 3, 7), date(2026, 3, 8)])

    def test_sparse_data_does_not_mutate_existing_baseline(self):
        today = date(2026, 3, 6)
        WakeBaselineState.objects.create(
            user=self.user,
            baseline_minutes=390,
            baseline_time=datetime.strptime("06:30", "%H:%M").time(),
            baseline_timezone="UTC",
        )
        self._create_interaction(local_date=today - timedelta(days=2), hour=6, minute=15, timezone_name="UTC")
        self._create_interaction(local_date=today - timedelta(days=1), hour=6, minute=20, timezone_name="UTC")
        self._create_interaction(local_date=today, hour=6, minute=10, timezone_name="UTC")

        payload = sync_wake_baseline_for_user(self.user)
        state = WakeBaselineState.objects.get(user=self.user)

        self.assertEqual(state.baseline_minutes, 390)
        self.assertEqual(state.last_update_reason, "insufficient_samples")
        self.assertTrue(payload["is_available"])

    def test_outlier_is_excluded_from_baseline(self):
        today = date(2026, 3, 6)
        regular_times = [(6, 10), (6, 20), (6, 15), (6, 25), (6, 30), (6, 18)]
        for index, (hour, minute) in enumerate(regular_times):
            self._create_interaction(
                local_date=today - timedelta(days=index),
                hour=hour,
                minute=minute,
                timezone_name="UTC",
            )
        self._create_interaction(local_date=today - timedelta(days=6), hour=23, minute=0, timezone_name="UTC")

        payload = sync_wake_baseline_for_user(self.user)
        state = WakeBaselineState.objects.get(user=self.user)

        self.assertEqual(state.last_valid_sample_count, 6)
        self.assertTrue(360 <= int(payload["baseline_minutes"]) <= 390)

    def test_baseline_updates_when_5_of_7_days_deviate(self):
        today = date(2026, 3, 6)
        WakeBaselineState.objects.create(
            user=self.user,
            baseline_minutes=360,
            baseline_time=datetime.strptime("06:00", "%H:%M").time(),
            baseline_timezone="UTC",
        )
        shifted_times = [(8, 0), (8, 10), (8, 5), (8, 15), (8, 20), (8, 0), (8, 10)]
        for index, (hour, minute) in enumerate(shifted_times):
            self._create_interaction(
                local_date=today - timedelta(days=index),
                hour=hour,
                minute=minute,
                timezone_name="UTC",
            )

        payload = sync_wake_baseline_for_user(self.user)
        state = WakeBaselineState.objects.get(user=self.user)

        self.assertEqual(state.last_update_reason, "behavior_shift_5_of_7")
        self.assertTrue(480 <= int(state.baseline_minutes) <= 500)
        self.assertEqual(payload["last_update_reason"], "behavior_shift_5_of_7")

    def test_generation_shifts_only_inferred_items_and_keeps_explicit_times(self):
        explicit_task, inferred_task = self._create_goal_with_tasks_for_schedule_tests()
        WakeBaselineState.objects.create(
            user=self.user,
            baseline_minutes=330,
            baseline_time=datetime.strptime("05:30", "%H:%M").time(),
            baseline_timezone="UTC",
            last_update_reason="initial_inference",
            last_sample_count=7,
            last_valid_sample_count=7,
        )

        task_list, created = get_or_create_today_task_list(self.user, timezone.localdate())
        self.assertTrue(created)

        explicit_item = task_list.tasks.get(goal_task=explicit_task)
        inferred_item = task_list.tasks.get(goal_task=inferred_task)
        self.assertEqual(explicit_item.time_slot, "evening")
        self.assertEqual(explicit_item.suggested_time.strftime("%H:%M"), "21:15")
        self.assertEqual(inferred_item.time_slot, "morning")
        self.assertIsNotNone(inferred_item.suggested_time)
        self.assertEqual(task_list.schedule_constraints["wake_baseline"]["baseline_minutes"], 330)


class DisciplineStreakLifecycleTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="discipline-streak@test.com",
            password="Password@123",
        )
        self.client.force_authenticate(self.user)

    def test_update_streak_resets_after_missed_day_gap(self):
        streak, _ = DisciplineStreak.objects.get_or_create(user=self.user)
        start_day = timezone.localdate() - timedelta(days=3)
        return_day = timezone.localdate() - timedelta(days=1)

        streak.update_streak(start_day, all_tasks_completed=True)
        streak.update_streak(return_day, all_tasks_completed=True)
        streak.refresh_from_db()

        self.assertEqual(streak.current_streak_days, 1)
        self.assertEqual(streak.current_streak_start, return_day)
        self.assertEqual(streak.longest_streak_days, 1)
        self.assertEqual(streak.total_perfect_days, 2)

    def test_streak_endpoint_reconciles_stale_streak_with_daily_task_history(self):
        today = timezone.localdate()
        completed_day = today - timedelta(days=2)
        missed_day = today - timedelta(days=1)

        DailyTaskList.objects.create(
            user=self.user,
            date=completed_day,
            total_tasks=1,
            completed_tasks=1,
            completion_percentage=100,
            is_fully_completed=True,
            status="completed",
        )
        DailyTaskList.objects.create(
            user=self.user,
            date=missed_day,
            total_tasks=1,
            completed_tasks=0,
            completion_percentage=0,
            is_fully_completed=False,
            status="pending",
        )

        DisciplineStreak.objects.update_or_create(
            user=self.user,
            defaults={
                "current_streak_days": 9,
                "current_streak_start": completed_day - timedelta(days=8),
                "longest_streak_days": 9,
                "longest_streak_start": completed_day - timedelta(days=8),
                "longest_streak_end": completed_day,
                "total_perfect_days": 9,
                "total_days_tracked": 9,
                "last_tracked_date": completed_day,
            },
        )

        response = self.client.get("/routines/streak/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["streak"]["current_streak_days"], 0)
        self.assertEqual(response.data["streak"]["longest_streak_days"], 1)
        self.assertEqual(response.data["streak"]["total_perfect_days"], 1)
        self.assertEqual(response.data["streak"]["total_days_tracked"], 2)

    def test_streak_endpoint_preserves_consecutive_completed_day_growth(self):
        today = timezone.localdate()
        first_day = today - timedelta(days=2)
        second_day = today - timedelta(days=1)

        DailyTaskList.objects.create(
            user=self.user,
            date=first_day,
            total_tasks=1,
            completed_tasks=1,
            completion_percentage=100,
            is_fully_completed=True,
            status="completed",
        )
        DailyTaskList.objects.create(
            user=self.user,
            date=second_day,
            total_tasks=1,
            completed_tasks=1,
            completion_percentage=100,
            is_fully_completed=True,
            status="completed",
        )

        response = self.client.get("/routines/streak/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["streak"]["current_streak_days"], 2)
        self.assertEqual(response.data["streak"]["longest_streak_days"], 2)
