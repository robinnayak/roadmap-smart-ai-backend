from datetime import timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from authentication.models import CustomUser
from events.models import Event
from routine.services import _fetch_day_event_constraints, _get_event_occurrences_for_day


class EventApiTests(APITestCase):
    def setUp(self):
        self.owner = CustomUser.objects.create_user(
            email="events-owner@test.com",
            password="Password@123",
        )
        self.other_user = CustomUser.objects.create_user(
            email="events-other@test.com",
            password="Password@123",
        )

    def _auth_owner(self):
        self.client.force_authenticate(self.owner)

    def _create_event(self, **overrides):
        payload = {
            "title": "Office Hours",
            "description": "Weekday office block",
            "event_type": "recurring",
            "start_at": "2026-03-09T09:00:00+05:45",
            "end_at": "2026-03-09T17:00:00+05:45",
            "is_all_day": False,
            "timezone": "Asia/Katmandu",
            "recurrence": {
                "frequency": "weekly",
                "interval": 1,
                "by_weekday": ["MON", "TUE", "WED", "THU", "FRI"],
                "until_date": "2026-12-31",
                "count": None,
            },
            "routine_constraint": {
                "constraint_mode": "hard",
                "buffer_before_minutes": 15,
                "buffer_after_minutes": 15,
                "routine_policy": "block",
            },
        }
        payload.update(overrides)
        return self.client.post("/events/", data=payload, format="json")

    def test_create_one_time_event_happy_path(self):
        self._auth_owner()
        response = self._create_event(
            title="Evening Party",
            event_type="one_time",
            start_at="2026-03-14T19:00:00+05:45",
            end_at="2026-03-14T23:30:00+05:45",
            recurrence=None,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["event_type"], "one_time")
        self.assertIsNone(response.data["recurrence"])
        self.assertTrue(Event.objects.filter(id=response.data["id"], user=self.owner).exists())

    def test_create_recurring_event_happy_path(self):
        self._auth_owner()
        response = self._create_event()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["event_type"], "recurring")
        self.assertEqual(response.data["recurrence"]["frequency"], "weekly")
        list_response = self.client.get("/events/")
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(list_response.data), 1)

    def test_unauthenticated_create_is_rejected(self):
        response = self._create_event()
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_non_owner_detail_access_returns_404(self):
        event = Event.objects.create(
            user=self.owner,
            title="Private Event",
            description="Hidden",
            event_type="one_time",
            start_at=timezone.now(),
            end_at=timezone.now() + timedelta(hours=1),
            timezone="UTC",
            recurrence=None,
            routine_constraint={"constraint_mode": "hard", "buffer_before_minutes": 0, "buffer_after_minutes": 0, "routine_policy": "block"},
        )
        self.client.force_authenticate(self.other_user)
        response = self.client.get(f"/events/{event.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_invalid_recurrence_weekly_requires_by_weekday(self):
        self._auth_owner()
        response = self._create_event(
            recurrence={
                "frequency": "weekly",
                "interval": 1,
                "until_date": "2026-12-31",
                "count": None,
            }
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("by_weekday", response.data)

    def test_invalid_date_range_end_before_start(self):
        self._auth_owner()
        response = self._create_event(
            event_type="one_time",
            start_at="2026-03-15T21:00:00+05:45",
            end_at="2026-03-15T20:00:00+05:45",
            recurrence=None,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("end_at", str(response.data))

    def test_range_filters_events_by_intersection(self):
        self._auth_owner()
        self._create_event(
            title="Travel",
            event_type="multi_day",
            start_at="2026-04-10T08:00:00+05:45",
            end_at="2026-04-13T22:00:00+05:45",
            recurrence=None,
        )
        self._create_event(
            title="Later Event",
            event_type="one_time",
            start_at="2026-05-20T10:00:00+05:45",
            end_at="2026-05-20T12:00:00+05:45",
            recurrence=None,
        )

        response = self.client.get("/events/range/?start_date=2026-04-11&end_date=2026-04-12")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["occurrences"]), 1)
        self.assertEqual(response.data["occurrences"][0]["title"], "Travel")

    def test_range_expands_weekly_recurrence(self):
        self._auth_owner()
        self._create_event(
            recurrence={
                "frequency": "weekly",
                "interval": 1,
                "by_weekday": ["MON", "WED"],
                "until_date": "2026-03-31",
                "count": None,
            }
        )
        response = self.client.get("/events/range/?start_date=2026-03-09&end_date=2026-03-15&timezone=Asia/Katmandu")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        starts = [item["start_at"] for item in response.data["occurrences"]]
        self.assertEqual(len(starts), 2)
        self.assertTrue(starts[0].startswith("2026-03-09T09:00:00"))
        self.assertTrue(starts[1].startswith("2026-03-11T09:00:00"))

    def test_all_day_event_normalizes_to_local_day_boundaries(self):
        self._auth_owner()
        response = self._create_event(
            title="Holiday",
            event_type="one_time",
            start_at="2026-03-14T10:30:00+05:45",
            end_at="2026-03-14T11:00:00+05:45",
            is_all_day=True,
            recurrence=None,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        event = Event.objects.get(id=response.data["id"])
        event_tz = ZoneInfo("Asia/Katmandu")
        self.assertEqual(event.start_at.astimezone(event_tz).isoformat(), "2026-03-14T00:00:00+05:45")
        self.assertEqual(event.end_at.astimezone(event_tz).isoformat(), "2026-03-14T23:59:59.999999+05:45")

        range_response = self.client.get("/events/range/?start_date=2026-03-14&end_date=2026-03-14&timezone=Asia/Katmandu")
        self.assertEqual(range_response.status_code, status.HTTP_200_OK)
        self.assertEqual(range_response.data["occurrences"][0]["start_at"], "2026-03-14T00:00:00+05:45")
        self.assertEqual(range_response.data["occurrences"][0]["end_at"], "2026-03-14T23:59:59.999999+05:45")

    def test_unsupported_recurrence_frequency_is_rejected_clearly(self):
        self._auth_owner()
        response = self._create_event(
            recurrence={
                "frequency": "yearly",
                "interval": 1,
                "count": 2,
            }
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("frequency", response.data)

    def test_range_overlap_metadata(self):
        self._auth_owner()
        self._create_event(
            title="Party",
            event_type="one_time",
            start_at="2026-03-14T19:00:00+05:45",
            end_at="2026-03-14T23:30:00+05:45",
            recurrence=None,
        )
        self._create_event(
            title="Dinner",
            event_type="one_time",
            start_at="2026-03-14T21:00:00+05:45",
            end_at="2026-03-14T22:30:00+05:45",
            recurrence=None,
        )
        response = self.client.get("/events/range/?start_date=2026-03-14&end_date=2026-03-14&timezone=Asia/Katmandu")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["occurrences"]), 2)
        overlaps = [item["overlap"]["has_overlap"] for item in response.data["occurrences"]]
        self.assertEqual(overlaps, [True, True])

    def test_range_returns_true_event_times_while_routine_constraints_apply_buffer_once(self):
        self._auth_owner()
        self._create_event(
            title="Buffered Meeting",
            event_type="one_time",
            start_at="2026-03-14T10:00:00+05:45",
            end_at="2026-03-14T11:00:00+05:45",
            recurrence=None,
        )
        response = self.client.get("/events/range/?start_date=2026-03-14&end_date=2026-03-14&timezone=Asia/Katmandu")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["occurrences"][0]["start_at"], "2026-03-14T10:00:00+05:45")

        event = Event.objects.get(user=self.owner, title="Buffered Meeting")
        occurrences = _get_event_occurrences_for_day(self.owner, event.start_at.date())
        constraints = _fetch_day_event_constraints(self.owner, event.start_at.date(), occurrences)
        self.assertEqual(
            constraints["occupied_windows"][0]["start_at"].isoformat(),
            "2026-03-14T09:45:00+05:45",
        )
