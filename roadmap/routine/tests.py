from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from authentication.models import CustomUser
from goal.models import Goal, Milestone, SubGoal, Task
from routine.models import DailyTaskList, DailyTaskItem, HabitTracker
from routine.services import get_or_create_today_task_list


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

        response = self.client.post(f"/routines/tasks/{daily_item.id}/complete/", data={})
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


class DailyTaskGenerationTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="schedule@test.com",
            password="Password@123",
        )

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
        self.assertEqual(len(habit_items), 1)
        self.assertEqual(len(goal_items), 3)

        by_task_id = {str(i.goal_task_id): i for i in goal_items if i.goal_task_id}
        self.assertEqual(by_task_id[str(task_preferred_evening.id)].time_slot, "evening")
        self.assertEqual(by_task_id[str(task_inferred_evening.id)].time_slot, "evening")
        self.assertEqual(by_task_id[str(task_fallback_afternoon.id)].time_slot, "afternoon")
