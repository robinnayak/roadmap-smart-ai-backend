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

    def _create_goal_with_subgoal(self, title: str, priority: str = "medium", status: str = "in_progress"):
        today = timezone.localdate()
        goal = Goal.objects.create(
            user=self.user,
            title=title,
            description=f"{title} description",
            primary_category="career",
            priority=priority,
            target_date=today + timedelta(days=60),
            status=status,
        )
        milestone = Milestone.objects.create(
            goal=goal,
            title=f"{title} Milestone",
            display_order=1,
            priority=priority,
            status="in_progress",
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
        self.assertEqual(len(habit_items), 1)
        self.assertEqual(len(goal_items), 3)

        by_task_id = {str(i.goal_task_id): i for i in goal_items if i.goal_task_id}
        self.assertEqual(by_task_id[str(task_preferred_evening.id)].time_slot, "evening")
        self.assertEqual(by_task_id[str(task_inferred_evening.id)].time_slot, "evening")
        self.assertEqual(by_task_id[str(task_fallback_afternoon.id)].time_slot, "afternoon")

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
