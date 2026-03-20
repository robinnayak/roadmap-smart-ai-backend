from datetime import timedelta
from unittest.mock import patch

from django.db import IntegrityError
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from authentication.models import CustomUser, Profile
from journal.models import AutoPhraseUsage, JournalEntry
from journal.utils import build_locked_at


class JournalApiTests(APITestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(email="journal@test.com", password="Password@123")
        self.client.force_authenticate(self.user)
        self.base_headers = {"HTTP_X_USER_TIMEZONE": "Asia/Kathmandu"}

    def test_create_and_update_entry(self):
        date_value = timezone.localdate().isoformat()
        create_payload = {
            "full_day_input": "Morning study, afternoon stress, evening gratitude and planning.",
            "reflection_raw": "I made good progress today",
            "struggle_raw": "I felt stressed in the afternoon",
            "tomorrow_priority_raw": "Complete algorithm practice",
            "gratitude_raw": "Grateful for family support",
            "parsed_via": "ollama_frontend",
        }
        create_resp = self.client.put(f"/journal/entries/?date={date_value}", create_payload, format="json", **self.base_headers)
        self.assertEqual(create_resp.status_code, status.HTTP_200_OK)
        self.assertIn("entry", create_resp.data)
        self.assertEqual(create_resp.data["entry"]["entry_date"], date_value)
        self.assertEqual(create_resp.data["entry"]["full_day_input"], create_payload["full_day_input"])
        self.assertEqual(create_resp.data["entry"]["parsed_via"], "ollama_frontend")

        update_resp = self.client.put(
            f"/journal/entries/?date={date_value}",
            {"reflection_raw": "I made even better progress today"},
            format="json",
            **self.base_headers,
        )
        self.assertEqual(update_resp.status_code, status.HTTP_200_OK)
        self.assertIn("better progress", update_resp.data["entry"]["reflection_raw"])

    def test_unique_user_entry_date(self):
        today = timezone.localdate()
        locked_at = timezone.now() + timedelta(hours=6)
        JournalEntry.objects.create(user=self.user, entry_date=today, locked_at=locked_at)
        with self.assertRaises(IntegrityError):
            JournalEntry.objects.create(user=self.user, entry_date=today, locked_at=locked_at)

    def test_lock_enforcement_returns_403(self):
        past_date = timezone.localdate() - timedelta(days=2)
        entry = JournalEntry.objects.create(
            user=self.user,
            entry_date=past_date,
            reflection_raw="old",
            locked_at=timezone.now() - timedelta(minutes=1),
        )

        response = self.client.put(
            f"/journal/entries/?date={entry.entry_date.isoformat()}",
            {"reflection_raw": "attempt update", "full_day_input": "blocked full day update"},
            format="json",
            **self.base_headers,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["code"], "entry_locked")

    def test_timezone_correctness_uses_header_and_locked_at(self):
        profile = Profile.objects.get(user=self.user)
        profile.timezone = "UTC"
        profile.save(update_fields=["timezone"])

        response = self.client.get("/journal/entries/", **self.base_headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["timezone"], "Asia/Kathmandu")

        entry_date = response.data["today_local_date"]
        create_resp = self.client.put(
            f"/journal/entries/?date={entry_date}",
            {"reflection_raw": "timezone test"},
            format="json",
            **self.base_headers,
        )
        self.assertEqual(create_resp.status_code, status.HTTP_200_OK)

        entry = JournalEntry.objects.get(user=self.user, entry_date=entry_date)
        expected_locked_at = build_locked_at(entry.entry_date, "Asia/Kathmandu")
        self.assertEqual(entry.locked_at, expected_locked_at)

    def test_autophrase_rate_limit(self):
        for idx in range(20):
            ok = self.client.post(
                "/journal/auto-phrase/",
                {"field": "reflection", "text": f"raw text {idx}"},
                format="json",
                **self.base_headers,
            )
            self.assertEqual(ok.status_code, status.HTTP_200_OK)

        blocked = self.client.post(
            "/journal/auto-phrase/",
            {"field": "reflection", "text": "blocked"},
            format="json",
            **self.base_headers,
        )
        self.assertEqual(blocked.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(blocked.data["code"], "auto_phrase_rate_limited")

    def test_search_pagination_filters_and_highlight(self):
        today = timezone.localdate()
        for idx in range(25):
            text = "I had progress in coding" if idx % 2 == 0 else "I felt stressed and tired"
            sentiment = "positive" if idx % 2 == 0 else "negative"
            JournalEntry.objects.create(
                user=self.user,
                entry_date=today - timedelta(days=idx),
                reflection_raw=text,
                sentiment_label=sentiment,
                tags=["coding"],
                locked_at=timezone.now() + timedelta(days=1),
            )

        response = self.client.get(
            "/journal/search/?q=progress&field=reflection&sentiment=positive&page=1&page_size=5"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 5)
        self.assertIn("<mark>", response.data["results"][0]["snippet"])

    def test_dates_pagination(self):
        start = timezone.localdate()
        for idx in range(70):
            JournalEntry.objects.create(
                user=self.user,
                entry_date=start - timedelta(days=idx),
                reflection_raw=f"entry {idx}",
                locked_at=timezone.now() + timedelta(days=1),
            )

        page_one = self.client.get("/journal/dates/?page=1&page_size=20")
        page_two = self.client.get("/journal/dates/?page=2&page_size=20")

        self.assertEqual(page_one.status_code, status.HTTP_200_OK)
        self.assertEqual(page_two.status_code, status.HTTP_200_OK)
        self.assertEqual(len(page_one.data["results"]), 20)
        self.assertEqual(len(page_two.data["results"]), 20)

    def test_put_saves_full_day_input_metadata(self):
        date_value = timezone.localdate().isoformat()
        payload = {
            "full_day_input": "I woke up late, had a difficult meeting, then planned tomorrow and felt thankful at dinner.",
            "reflection_raw": "I still made meaningful progress despite delays.",
            "struggle_raw": "I felt pressured in the meeting.",
            "tomorrow_priority_raw": "Start early and finish proposal draft.",
            "gratitude_raw": "Thankful for team support.",
            "parsed_via": "ollama_frontend",
        }
        response = self.client.put(f"/journal/entries/?date={date_value}", payload, format="json", **self.base_headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["entry"]["full_day_input"], payload["full_day_input"])
        self.assertEqual(response.data["entry"]["parsed_via"], "ollama_frontend")

    def test_full_day_input_backfills_blank_structured_fields(self):
        date_value = timezone.localdate().isoformat()
        payload = {
            "full_day_input": "Morning study progress. Difficult client meeting. Tomorrow finish the proposal first. Thankful for my family at dinner.",
        }
        response = self.client.put(f"/journal/entries/?date={date_value}", payload, format="json", **self.base_headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        entry = response.data["entry"]
        self.assertIn("Morning study progress", entry["reflection_raw"])
        self.assertIn("Difficult client meeting", entry["struggle_raw"])
        self.assertIn("Tomorrow finish the proposal first", entry["tomorrow_priority_raw"])
        self.assertIn("Thankful for my family at dinner", entry["gratitude_raw"])
        self.assertEqual(entry["parsed_via"], "backend_heuristic")
        self.assertIsNotNone(entry["parsed_at"])

    def test_parsed_via_rejects_unknown_values(self):
        date_value = timezone.localdate().isoformat()
        response = self.client.put(
            f"/journal/entries/?date={date_value}",
            {"reflection_raw": "test", "parsed_via": "unknown_parser"},
            format="json",
            **self.base_headers,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("parsed_via", response.data)

    @patch("journal.views.ai_or_fallback_summary_refine")
    def test_refine_summary_success(self, mock_refine):
        mock_refine.return_value = "I am grateful for this beautiful life. Today I made strong progress."
        response = self.client.post(
            "/journal/refine-summary/",
            {"text": "i am grateful for life , today progress"},
            format="json",
            **self.base_headers,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["refined_text"],
            "I am grateful for this beautiful life. Today I made strong progress.",
        )
        self.assertEqual(response.data["daily_limit"], 20)
        self.assertEqual(response.data["remaining_today"], 19)
        mock_refine.assert_called_once()

    def test_refine_summary_rejects_blank_text(self):
        response = self.client.post(
            "/journal/refine-summary/",
            {"text": ""},
            format="json",
            **self.base_headers,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_refine_summary_rate_limit(self):
        for idx in range(20):
            ok = self.client.post(
                "/journal/refine-summary/",
                {"text": f"raw summary {idx}"},
                format="json",
                **self.base_headers,
            )
            self.assertEqual(ok.status_code, status.HTTP_200_OK)

        blocked = self.client.post(
            "/journal/refine-summary/",
            {"text": "blocked summary"},
            format="json",
            **self.base_headers,
        )
        self.assertEqual(blocked.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(blocked.data["code"], "summary_refine_rate_limited")

    def test_auto_phrase_and_summary_refine_have_independent_quotas(self):
        for idx in range(20):
            ok = self.client.post(
                "/journal/auto-phrase/",
                {"field": "reflection", "text": f"raw text {idx}"},
                format="json",
                **self.base_headers,
            )
            self.assertEqual(ok.status_code, status.HTTP_200_OK)

        blocked_auto_phrase = self.client.post(
            "/journal/auto-phrase/",
            {"field": "reflection", "text": "blocked"},
            format="json",
            **self.base_headers,
        )
        self.assertEqual(blocked_auto_phrase.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

        summary_response = self.client.post(
            "/journal/refine-summary/",
            {"text": "i am still allowed here"},
            format="json",
            **self.base_headers,
        )
        self.assertEqual(summary_response.status_code, status.HTTP_200_OK)
        self.assertEqual(summary_response.data["remaining_today"], 19)
        self.assertEqual(
            AutoPhraseUsage.objects.filter(user=self.user, usage_date=timezone.localdate()).count(),
            2,
        )

