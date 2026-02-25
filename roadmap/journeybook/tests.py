from __future__ import annotations

import shutil
import tempfile
from datetime import date, timedelta
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from goal.models import Goal
from journal.models import JournalEntry
from journeybook.models import BookChapter, JourneyBook
from journeybook.services.data_collector import DataCollector
from journeybook.services.metrics_calculator import MetricsCalculator

TEMP_MEDIA_ROOT = tempfile.mkdtemp(prefix="journeybook_test_media_")


@override_settings(MEDIA_ROOT=TEMP_MEDIA_ROOT)
class JourneyBookAPITestCase(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.client = APIClient()
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            email="user1@example.com",
            password="TestPass123!",
        )
        self.other_user = user_model.objects.create_user(
            email="user2@example.com",
            password="TestPass123!",
        )
        self.client.force_authenticate(user=self.user)

    def _create_goal(
        self,
        *,
        user=None,
        status: str = "not_started",
        start_days_ago: int = 0,
        target_days_from_now: int = 30,
        title: str = "Journey Goal",
    ) -> Goal:
        user = user or self.user
        return Goal.objects.create(
            user=user,
            title=title,
            primary_category="personal",
            status=status,
            start_date=date.today() - timedelta(days=start_days_ago),
            target_date=date.today() + timedelta(days=target_days_from_now),
        )

    def _create_journal_entry(
        self,
        *,
        entry_date: date,
        user=None,
        sentiment_score: float = 0.0,
        reflection_raw: str = "This is a meaningful reflection for testing.",
    ) -> JournalEntry:
        user = user or self.user
        sentiment_label = "negative" if sentiment_score < 0 else "neutral"
        return JournalEntry.objects.create(
            user=user,
            entry_date=entry_date,
            reflection_raw=reflection_raw,
            struggle_raw="A testing struggle entry.",
            sentiment_score=sentiment_score,
            sentiment_label=sentiment_label,
            locked_at=timezone.now() + timedelta(days=1),
        )

    def _create_book(
        self,
        *,
        user=None,
        goal=None,
        status_value: str = JourneyBook.STATUS_READY,
        with_pdf: bool = False,
        created_at=None,
    ) -> JourneyBook:
        user = user or self.user
        goal = goal or self._create_goal(user=user, status="completed")
        book = JourneyBook.objects.create(
            user=user,
            goal=goal,
            book_type=JourneyBook.BOOK_TYPE_COMPLETE,
            status=status_value,
            data_start_date=date.today() - timedelta(days=10),
            data_end_date=date.today(),
            days_of_data=11,
        )
        if with_pdf:
            book.pdf_file.save(
                f"book_{book.id}.pdf",
                ContentFile(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF"),
                save=True,
            )
        if created_at is not None:
            JourneyBook.objects.filter(id=book.id).update(created_at=created_at)
            book.refresh_from_db()
        return book

    def test_eligibility_less_than_7_days(self):
        goal = self._create_goal(status="not_started", start_days_ago=0)
        url = reverse("journeybook:journeybook-eligibility")
        response = self.client.get(url, {"goal_id": str(goal.id)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertFalse(payload["can_generate_complete"])
        self.assertFalse(payload["can_generate_in_progress"])
        self.assertIsNotNone(payload["reason_blocked"])

    def test_eligibility_7_to_179_days(self):
        goal = self._create_goal(status="not_started", start_days_ago=20)
        url = reverse("journeybook:journeybook-eligibility")
        response = self.client.get(url, {"goal_id": str(goal.id)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertFalse(payload["can_generate_complete"])
        self.assertTrue(payload["can_generate_in_progress"])
        self.assertFalse(payload["can_choose_type"])

    def test_eligibility_180_plus_days(self):
        goal = self._create_goal(status="not_started", start_days_ago=200)
        url = reverse("journeybook:journeybook-eligibility")
        response = self.client.get(url, {"goal_id": str(goal.id)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertTrue(payload["can_generate_complete"])
        self.assertTrue(payload["can_generate_in_progress"])
        self.assertTrue(payload["can_choose_type"])

    def test_eligibility_completed_goal(self):
        goal = self._create_goal(status="completed", start_days_ago=0)
        url = reverse("journeybook:journeybook-eligibility")
        response = self.client.get(url, {"goal_id": str(goal.id)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertTrue(payload["can_generate_complete"])
        self.assertTrue(payload["can_generate_in_progress"])

    @patch("journeybook.views.JourneyBookViewSet._generate_sync")
    def test_generate_creates_record(self, mock_generate_sync):
        goal = self._create_goal(status="completed", start_days_ago=0)
        mock_generate_sync.return_value = None

        url = reverse("journeybook:journeybook-list")
        payload = {
            "goal_id": str(goal.id),
            "book_type": "in_progress",
            "privacy_settings": {"exclude_journal_ids": []},
        }
        response = self.client.post(url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        book = JourneyBook.objects.filter(user=self.user).first()
        self.assertIsNotNone(book)
        self.assertIn(book.status, [JourneyBook.STATUS_QUEUED, JourneyBook.STATUS_GENERATING])

    def test_generate_rate_limit(self):
        goal = self._create_goal(status="completed")
        self._create_book(
            goal=goal,
            status_value=JourneyBook.STATUS_QUEUED,
            with_pdf=False,
        )

        url = reverse("journeybook:journeybook-list")
        payload = {"goal_id": str(goal.id), "book_type": "in_progress"}
        response = self.client.post(url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(response.json().get("error"), "Rate limit")
        self.assertIn("next_allowed_at", response.json())

    def test_download_requires_ownership(self):
        goal = self._create_goal(user=self.other_user, status="completed")
        book = self._create_book(user=self.other_user, goal=goal, with_pdf=True)

        self.client.force_authenticate(user=self.user)
        url = reverse("journeybook:journeybook-download", args=[str(book.id)])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_download_returns_pdf(self):
        goal = self._create_goal(status="completed")
        book = self._create_book(goal=goal, with_pdf=True, status_value=JourneyBook.STATUS_READY)

        url = reverse("journeybook:journeybook-download", args=[str(book.id)])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("application/pdf", response.get("Content-Type", ""))

    def test_download_not_ready_returns_404(self):
        goal = self._create_goal(status="in_progress")
        book = self._create_book(goal=goal, status_value=JourneyBook.STATUS_GENERATING)

        url = reverse("journeybook:journeybook-download", args=[str(book.id)])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_dip_detection_finds_gap(self):
        start = date.today() - timedelta(days=20)
        journals = []
        for i in range(5):
            journals.append(
                {
                    "entry_date": start + timedelta(days=i),
                    "reflection_raw": "A reflective entry with enough characters.",
                    "struggle_raw": "Some struggle text.",
                    "sentiment_score": 0.1,
                    "total_word_count": 120,
                }
            )
        journals.append(
            {
                "entry_date": start + timedelta(days=12),
                "reflection_raw": "Returned after a long gap with a strong note.",
                "struggle_raw": "Back again.",
                "sentiment_score": 0.2,
                "total_word_count": 140,
            }
        )

        result = MetricsCalculator({"journals": journals}).calculate_all()
        self.assertEqual(result["dip"]["dip_type"], "missed_days")
        self.assertGreaterEqual(result["dip"]["days_missed"], 6)

    def test_dip_detection_fallback_sentiment(self):
        start = date.today() - timedelta(days=10)
        journals = []
        for i in range(10):
            journals.append(
                {
                    "entry_date": start + timedelta(days=i),
                    "reflection_raw": "Consecutive day reflection with enough detail.",
                    "struggle_raw": "Consecutive day struggle.",
                    "sentiment_score": -0.8 if 2 <= i <= 8 else 0.2,
                    "total_word_count": 100,
                }
            )

        result = MetricsCalculator({"journals": journals}).calculate_all()
        self.assertEqual(result["dip"]["dip_type"], "low_sentiment")

    def test_derived_milestones_first_step(self):
        entry_day = date.today() - timedelta(days=3)
        journals = [
            {
                "entry_date": entry_day,
                "reflection_raw": "First milestone reflection with enough detail.",
                "struggle_raw": "Initial challenge text.",
                "sentiment_score": 0.1,
                "total_word_count": 100,
            }
        ]
        result = MetricsCalculator(
            {
                "user": self.user,
                "journals": journals,
                "streaks": {"longest_streak": 1, "last_entry_date": entry_day},
            }
        ).calculate_all()
        self.assertTrue(
            any(m["trigger_type"] == "first_journal_entry" for m in result["derived_milestones"])
        )

    def test_derived_milestones_streak_7(self):
        entry_day = date.today() - timedelta(days=1)
        journals = [
            {
                "entry_date": entry_day,
                "reflection_raw": "Streak milestone reflection with enough detail.",
                "struggle_raw": "Streak challenge text.",
                "sentiment_score": 0.3,
                "total_word_count": 90,
            }
        ]
        result = MetricsCalculator(
            {
                "user": self.user,
                "journals": journals,
                "streaks": {"longest_streak": 7, "last_entry_date": entry_day},
            }
        ).calculate_all()
        self.assertTrue(any(m["trigger_type"] == "streak_7" for m in result["derived_milestones"]))

    def test_privacy_excludes_journal_ids(self):
        day_one = date.today() - timedelta(days=2)
        day_two = date.today() - timedelta(days=1)
        entry_one = self._create_journal_entry(entry_date=day_one)
        entry_two = self._create_journal_entry(entry_date=day_two)

        collector = DataCollector(
            self.user,
            privacy_settings={"exclude_journal_ids": [str(entry_one.id)]},
        )
        data = collector.collect_all_data()
        returned_ids = {str(row["id"]) for row in data["journals"]}

        self.assertEqual(len(returned_ids), 1)
        self.assertNotIn(str(entry_one.id), returned_ids)
        self.assertIn(str(entry_two.id), returned_ids)

    def test_delete_removes_file(self):
        goal = self._create_goal(status="completed")
        book = self._create_book(goal=goal, with_pdf=True, status_value=JourneyBook.STATUS_READY)
        file_name = book.pdf_file.name
        self.assertTrue(default_storage.exists(file_name))

        url = reverse("journeybook:journeybook-detail", args=[str(book.id)])
        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(JourneyBook.objects.filter(id=book.id).exists())
        self.assertFalse(default_storage.exists(file_name))

    @patch(
        "journeybook.services.pdf_builder.PDFBuilder.build",
        return_value=BytesIO(b"%PDF-1.4\njourney\n%%EOF"),
    )
    @patch(
        "journeybook.services.image_generator.ImageGenerator.generate_milestone_timeline",
        return_value=BytesIO(b"timeline"),
    )
    @patch(
        "journeybook.services.image_generator.ImageGenerator.generate_heatmap",
        return_value=BytesIO(b"heatmap"),
    )
    @patch(
        "journeybook.services.image_generator.ImageGenerator.generate_streak_chart",
        return_value=BytesIO(b"streak"),
    )
    @patch(
        "journeybook.services.image_generator.ImageGenerator.generate_sentiment_chart",
        return_value=BytesIO(b"sentiment"),
    )
    @patch(
        "journeybook.services.image_generator.ImageGenerator.generate_completion_chart",
        return_value=BytesIO(b"completion"),
    )
    @patch(
        "journeybook.services.ai_generator.AIGenerator.generate_motivational_page",
        return_value="Motivational page text for testing.",
    )
    @patch(
        "journeybook.services.ai_generator.AIGenerator.generate_chapter",
        return_value="Generated chapter text " * 50,
    )
    def test_book_chapter_saved_per_chapter(
        self,
        _mock_chapter,
        _mock_motivational,
        _mock_completion,
        _mock_sentiment,
        _mock_streak,
        _mock_heatmap,
        _mock_timeline,
        _mock_pdf,
    ):
        goal = self._create_goal(status="completed")
        url = reverse("journeybook:journeybook-list")
        payload = {
            "goal_id": str(goal.id),
            "book_type": "in_progress",
            "privacy_settings": {"exclude_journal_ids": []},
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        book = JourneyBook.objects.filter(user=self.user).order_by("-created_at").first()
        self.assertIsNotNone(book)
        self.assertEqual(BookChapter.objects.filter(journey_book=book).count(), 5)
