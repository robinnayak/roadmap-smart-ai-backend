from datetime import date, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from authentication.models import CustomUser
from goal.models import Goal, Milestone, SubGoal, Task

from .engine import build_morning_message, get_or_create_daily_log, smart_pick
from .models import DailyRitualLog


class RitualEngineTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="ritual-engine@test.com",
            password="Password@123",
        )

    def test_smart_pick_avoids_previous_day_repeat(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        today = timezone.localdate()
        DailyRitualLog.objects.create(
            user=self.user,
            date=yesterday,
            shown_variants={"wake_on_time_bro": 0},
        )
        today_log = get_or_create_daily_log(self.user, today)

        chosen = smart_pick(self.user, "wake_on_time_bro", ["A", "B", "C"], log=today_log)

        self.assertEqual(chosen, "B")
        today_log.refresh_from_db()
        self.assertEqual(today_log.shown_variants["wake_on_time_bro"], 1)

    def test_build_morning_message_uses_previous_night_intent_and_reflection(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        previous_log = DailyRitualLog.objects.create(
            user=self.user,
            date=yesterday,
            tomorrow_intent="Ship the onboarding fix",
            yesterday_task_reflection="done",
            night_session_completed=True,
        )
        today_log = DailyRitualLog.objects.create(
            user=self.user,
            date=timezone.localdate(),
            wake_delta_minutes=0,
        )

        payload = build_morning_message(
            self.user,
            {
                "log": today_log,
                "previous_log": previous_log,
                "tone": "coach",
                "current_date": timezone.localdate(),
            },
        )

        self.assertEqual(payload["task_today"], "Ship the onboarding fix")
        self.assertIn("Ship the onboarding fix", payload["message"])


class RitualApiTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="ritual-api@test.com",
            password="Password@123",
        )
        self.other_user = CustomUser.objects.create_user(
            email="ritual-api-other@test.com",
            password="Password@123",
        )
        self.client.force_authenticate(self.user)

        goal = Goal.objects.create(
            user=self.user,
            title="Launch the ritual engine",
            description="Ship the backend loop",
            primary_category="career",
            status="in_progress",
            start_date=timezone.localdate() - timedelta(days=5),
            target_date=timezone.localdate() + timedelta(days=25),
        )
        milestone = Milestone.objects.create(
            goal=goal,
            title="Build the backend",
            display_order=1,
            status="in_progress",
        )
        subgoal = SubGoal.objects.create(
            milestone=milestone,
            title="Implement API endpoints",
            display_order=1,
            status="in_progress",
        )
        for index in range(8):
            Task.objects.create(
                subgoal=subgoal,
                title=f"Task {index}",
                status="pending" if index < 7 else "completed",
                display_order=index,
            )
        other_goal = Goal.objects.create(
            user=self.other_user,
            title="Other user goal",
            description="Should not leak",
            primary_category="career",
            status="in_progress",
            start_date=timezone.localdate(),
            target_date=timezone.localdate() + timedelta(days=10),
        )
        other_milestone = Milestone.objects.create(goal=other_goal, title="Other", display_order=1)
        other_subgoal = SubGoal.objects.create(milestone=other_milestone, title="Other", display_order=1)
        Task.objects.create(subgoal=other_subgoal, title="Other secret task", status="pending")

    def test_morning_message_requires_authentication(self):
        self.client.force_authenticate(user=None)
        response = self.client.get("/api/ritual/morning/message/", secure=True)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_tone_get_and_post_round_trip(self):
        get_response = self.client.get("/api/ritual/tone/", secure=True)
        self.assertEqual(get_response.status_code, status.HTTP_200_OK)
        self.assertEqual(get_response.data["tone"], "gentle")

        post_response = self.client.post("/api/ritual/tone/", data={"tone": "coach"}, format="json", secure=True)
        self.assertEqual(post_response.status_code, status.HTTP_200_OK)
        self.assertEqual(post_response.data["tone"], "coach")

    def test_goal_tasks_returns_max_six_active_titles(self):
        response = self.client.get("/api/ritual/goal-tasks/", secure=True)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["tasks"]), 6)
        self.assertNotIn("Other secret task", response.data["tasks"])
        self.assertNotIn("Task 7", response.data["tasks"])

    @patch("rituals.views.timezone.localdate")
    @patch("rituals.engine.timezone.localdate")
    def test_night_intent_feeds_next_morning_message(self, engine_localdate, views_localdate):
        day_one = date(2026, 4, 1)
        day_two = date(2026, 4, 2)

        engine_localdate.return_value = day_one
        views_localdate.return_value = day_one
        intent_response = self.client.post(
            "/api/ritual/night/intent/",
            data={"task": "Write the daily ritual tests", "alarm_time": "06:15"},
            format="json",
            secure=True,
        )
        self.assertEqual(intent_response.status_code, status.HTTP_200_OK)

        engine_localdate.return_value = day_two
        views_localdate.return_value = day_two
        morning_response = self.client.get("/api/ritual/morning/message/", secure=True)
        self.assertEqual(morning_response.status_code, status.HTTP_200_OK)
        self.assertEqual(morning_response.data["task_today"], "Write the daily ritual tests")
        self.assertIn("Write the daily ritual tests", morning_response.data["message"])
