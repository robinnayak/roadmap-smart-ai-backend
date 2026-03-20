from __future__ import annotations

import shutil
import tempfile
from datetime import date, timedelta
from io import BytesIO
from unittest.mock import MagicMock, patch

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
from journeybook.models import BookAsset, BookChapter, DerivedMilestone, JourneyBook
from journeybook.services.data_collector import DataCollector
from journeybook.services.demo_mode import build_demo_pdf_bytes
from journeybook.services.metrics_calculator import MetricsCalculator
from journeybook.services.pdf_builder import PDFBuilder

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
        goals=None,
        status_value: str = JourneyBook.STATUS_READY,
        with_pdf: bool = False,
        created_at=None,
        error_message: str = "",
        selection_mode: str | None = None,
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
            error_message=error_message,
            metadata={"selection_mode": selection_mode} if selection_mode else {},
        )
        selected_goals = goals or ([goal] if goal else [])
        if selected_goals:
            book.goals.set(selected_goals)
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
        self.assertEqual(payload["complete_unlock_reason"], "not_unlocked")
        self.assertEqual(payload["journal_days"], 0)
        self.assertGreaterEqual(payload["goal_age_days"], 1)
        self.assertFalse(payload["goal_completed_or_due"])
        self.assertEqual(payload["minimum_requirements"]["in_progress_min_days"], 7)
        self.assertEqual(
            payload["minimum_requirements"]["complete_min_days_if_goal_not_done_or_due"],
            180,
        )
        self.assertTrue(payload["minimum_requirements"]["uses_journal_entries"])
        self.assertTrue(payload["minimum_requirements"]["uses_goal_timeline"])

    def test_eligibility_7_to_179_days(self):
        goal = self._create_goal(status="not_started", start_days_ago=20)
        url = reverse("journeybook:journeybook-eligibility")
        response = self.client.get(url, {"goal_id": str(goal.id)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertFalse(payload["can_generate_complete"])
        self.assertTrue(payload["can_generate_in_progress"])
        self.assertFalse(payload["can_choose_type"])
        self.assertEqual(payload["complete_unlock_reason"], "not_unlocked")

    def test_eligibility_180_plus_days(self):
        goal = self._create_goal(status="not_started", start_days_ago=200)
        url = reverse("journeybook:journeybook-eligibility")
        response = self.client.get(url, {"goal_id": str(goal.id)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertTrue(payload["can_generate_complete"])
        self.assertTrue(payload["can_generate_in_progress"])
        self.assertTrue(payload["can_choose_type"])
        self.assertEqual(payload["complete_unlock_reason"], "long_journey")

    def test_eligibility_completed_goal(self):
        goal = self._create_goal(status="completed", start_days_ago=0)
        url = reverse("journeybook:journeybook-eligibility")
        response = self.client.get(url, {"goal_id": str(goal.id)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertTrue(payload["can_generate_complete"])
        self.assertTrue(payload["can_generate_in_progress"])
        self.assertTrue(payload["goal_completed_or_due"])
        self.assertEqual(payload["complete_unlock_reason"], "completed_goal")

    def test_eligibility_multi_goal_unlocks_when_any_goal_completed(self):
        completed_goal = self._create_goal(status="completed", start_days_ago=3, title="Done goal")
        active_goal = self._create_goal(status="in_progress", start_days_ago=3, title="Active goal")
        url = reverse("journeybook:journeybook-eligibility")
        response = self.client.get(
            url,
            [("goal_ids", str(active_goal.id)), ("goal_ids", str(completed_goal.id))],
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertTrue(payload["can_generate_complete"])
        self.assertEqual(payload["selection_mode"], "multiple")
        self.assertEqual(payload["goal_ids"], [str(active_goal.id), str(completed_goal.id)])

    def test_eligibility_all_goals_uses_all_user_goals(self):
        first_goal = self._create_goal(status="in_progress", start_days_ago=10)
        second_goal = self._create_goal(status="completed", start_days_ago=2)
        url = reverse("journeybook:journeybook-eligibility")
        response = self.client.get(url, {"include_all_goals": "true"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertEqual(payload["selection_mode"], "all")
        self.assertCountEqual(payload["goal_ids"], [str(first_goal.id), str(second_goal.id)])

    def test_eligibility_goal_due_unlocks_complete(self):
        goal = self._create_goal(status="in_progress", start_days_ago=1, target_days_from_now=-1)
        url = reverse("journeybook:journeybook-eligibility")
        response = self.client.get(url, {"goal_id": str(goal.id)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertTrue(payload["can_generate_complete"])
        self.assertTrue(payload["can_generate_in_progress"])
        self.assertTrue(payload["goal_completed_or_due"])
        self.assertEqual(payload["complete_unlock_reason"], "goal_due")

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

    @patch("journeybook.views.JourneyBookViewSet._generate_sync")
    def test_generate_multiple_goals_creates_selection(self, mock_generate_sync):
        first_goal = self._create_goal(status="in_progress", start_days_ago=15, title="Goal A")
        second_goal = self._create_goal(status="completed", start_days_ago=3, title="Goal B")
        mock_generate_sync.return_value = None

        url = reverse("journeybook:journeybook-list")
        payload = {
            "goal_ids": [str(first_goal.id), str(second_goal.id)],
            "book_type": "complete",
            "privacy_settings": {"exclude_journal_ids": []},
        }
        response = self.client.post(url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        book = JourneyBook.objects.get(user=self.user)
        self.assertEqual(book.goal_id, first_goal.id)
        self.assertEqual(book.metadata["selection_mode"], "multiple")
        self.assertCountEqual(book.goals.values_list("id", flat=True), [first_goal.id, second_goal.id])

    @patch("journeybook.views.JourneyBookViewSet._generate_sync")
    def test_generate_all_goals_creates_all_selection(self, mock_generate_sync):
        first_goal = self._create_goal(status="in_progress", start_days_ago=15, title="Goal A")
        second_goal = self._create_goal(status="completed", start_days_ago=3, title="Goal B")
        mock_generate_sync.return_value = None

        url = reverse("journeybook:journeybook-list")
        payload = {
            "include_all_goals": True,
            "book_type": "complete",
            "privacy_settings": {"exclude_journal_ids": []},
        }
        response = self.client.post(url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        book = JourneyBook.objects.get(user=self.user)
        self.assertEqual(book.metadata["selection_mode"], "all")
        self.assertCountEqual(book.goals.values_list("id", flat=True), [first_goal.id, second_goal.id])

    def test_generate_rejects_conflicting_goal_selection_inputs(self):
        goal = self._create_goal(status="completed", start_days_ago=0)
        url = reverse("journeybook:journeybook-list")
        payload = {
            "goal_id": str(goal.id),
            "goal_ids": [str(goal.id)],
            "book_type": "complete",
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("goal_ids", response.json())

    def test_generate_rejects_goal_not_owned_for_goal_ids(self):
        own_goal = self._create_goal(status="completed", start_days_ago=10)
        foreign_goal = self._create_goal(user=self.other_user, status="completed", start_days_ago=10)
        url = reverse("journeybook:journeybook-list")
        payload = {
            "goal_ids": [str(own_goal.id), str(foreign_goal.id)],
            "book_type": "complete",
        }
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("goal_ids", response.json())

    @patch("journeybook.views.JourneyBookViewSet._generate_sync", side_effect=ValueError("generation failure"))
    def test_generate_handles_sync_value_error_without_crashing(self, _mock_generate_sync):
        goal = self._create_goal(status="completed", start_days_ago=0)
        url = reverse("journeybook:journeybook-list")
        payload = {
            "goal_id": str(goal.id),
            "book_type": "in_progress",
            "privacy_settings": {"exclude_journal_ids": []},
        }

        response = self.client.post(url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.json()["code"], "journeybook_generation_failed")
        self.assertEqual(JourneyBook.objects.filter(user=self.user).count(), 1)

    @patch("journeybook.views.JourneyBookViewSet._generate_sync")
    def test_generate_returns_failed_contract_when_sync_generation_marks_failed_and_raises(
        self,
        mock_generate_sync,
    ):
        goal = self._create_goal(status="completed", start_days_ago=0)

        def _fail_generation(*args, **kwargs):
            book = kwargs["book"]
            book.mark_failed("provider unavailable")
            raise RuntimeError("provider unavailable")

        mock_generate_sync.side_effect = _fail_generation

        response = self.client.post(
            reverse("journeybook:journeybook-list"),
            {
                "goal_id": str(goal.id),
                "book_type": "in_progress",
                "privacy_settings": {"exclude_journal_ids": []},
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        payload = response.json()
        self.assertFalse(payload["success"])
        self.assertEqual(payload["code"], "journeybook_generation_failed")
        book = JourneyBook.objects.get(user=self.user)
        self.assertEqual(payload["book_id"], str(book.id))
        self.assertEqual(payload["status"], JourneyBook.STATUS_FAILED)
        self.assertEqual(book.status, JourneyBook.STATUS_FAILED)

    def test_generate_demo_mode_returns_payload_without_writes(self):
        url = reverse("journeybook:journeybook-list")
        payload = {
            "mode": "demo",
            "book_type": "in_progress",
        }
        response = self.client.post(url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["mode"], "demo")
        self.assertEqual(body["book_type"], "in_progress")
        self.assertGreater(len(body.get("chapters", [])), 0)
        self.assertEqual(JourneyBook.objects.count(), 0)

    def test_public_demo_preview_endpoint_is_unauthenticated(self):
        anon_client = APIClient()
        url = reverse("journeybook-demo-preview")
        response = anon_client.get(url, {"book_type": "complete"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["mode"], "demo")
        self.assertEqual(body["book_type"], "complete")
        self.assertEqual(body["source"], "demo_data")

    def test_base_endpoint_exposes_reportlab_readiness(self):
        anon_client = APIClient()
        response = anon_client.get("/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertIn("readiness", payload)
        self.assertIn("reportlab_available", payload["readiness"])

    def test_public_demo_preview_includes_generation_source_and_trim_spec(self):
        anon_client = APIClient()
        url = reverse("journeybook-demo-preview")
        response = anon_client.get(url, {"book_type": "in_progress", "trim_size": "7x10"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertIn("generation_source", body)
        self.assertIn(body["generation_source"]["overall"], ["ai", "fallback", "mixed"])
        self.assertIn("print_spec", body)
        self.assertEqual(body["print_spec"]["trim_size"], "7x10")
        self.assertGreater(len(body.get("chapters", [])), 0)
        self.assertIn("generation_source", body["chapters"][0])

    def test_public_demo_preview_invalid_trim_defaults_to_6x9(self):
        anon_client = APIClient()
        url = reverse("journeybook-demo-preview")
        response = anon_client.get(url, {"book_type": "complete", "trim_size": "invalid"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["print_spec"]["trim_size"], "6x9")

    @patch(
        "journeybook.services.demo_mode.PDFBuilder.build",
        return_value=BytesIO(b"%PDF-1.4\nmock-demo\n%%EOF"),
    )
    def test_public_demo_preview_pdf_is_unauthenticated_and_has_no_db_writes(self, _mock_pdf):
        anon_client = APIClient()
        url = reverse("journeybook-demo-preview-pdf")
        before_counts = {
            "books": JourneyBook.objects.count(),
            "chapters": BookChapter.objects.count(),
            "assets": BookAsset.objects.count(),
            "milestones": DerivedMilestone.objects.count(),
        }

        response = anon_client.get(url, {"book_type": "complete", "trim_size": "5.5x8.5"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("application/pdf", response.get("Content-Type", ""))
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertIn("journey_book_demo_complete_5_5x8_5.pdf", response.get("Content-Disposition", ""))

        after_counts = {
            "books": JourneyBook.objects.count(),
            "chapters": BookChapter.objects.count(),
            "assets": BookAsset.objects.count(),
            "milestones": DerivedMilestone.objects.count(),
        }
        self.assertEqual(after_counts, before_counts)

    @patch(
        "journeybook.services.demo_mode.PDFBuilder.build",
        return_value=BytesIO(b"%PDF-1.4\nmock-demo\n%%EOF"),
    )
    def test_public_demo_preview_pdf_invalid_trim_defaults_to_6x9(self, _mock_pdf):
        anon_client = APIClient()
        url = reverse("journeybook-demo-preview-pdf")
        response = anon_client.get(url, {"book_type": "complete", "trim_size": "bad-trim"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("journey_book_demo_complete_6x9.pdf", response.get("Content-Disposition", ""))

    @patch(
        "journeybook.views.build_demo_pdf_bytes",
        side_effect=RuntimeError("ReportLab is required to build Journey Book PDFs."),
    )
    def test_public_demo_preview_pdf_returns_503_when_pdf_engine_missing(self, _mock_pdf):
        anon_client = APIClient()
        url = reverse("journeybook-demo-preview-pdf")
        response = anon_client.get(url, {"book_type": "complete", "trim_size": "6x9"})

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        payload = response.json()
        self.assertEqual(payload["error_type"], "PDF_ENGINE_ERROR")
        self.assertEqual(payload["message"], "ReportLab is not installed in backend runtime.")

    @patch(
        "journeybook.services.demo_mode.PDFBuilder.build",
        side_effect=RuntimeError("ReportLab is required to build Journey Book PDFs."),
    )
    def test_build_demo_pdf_bytes_propagates_runtime_error_without_placeholder_pdf(self, _mock_pdf):
        with self.assertRaises(RuntimeError):
            build_demo_pdf_bytes(book_type="complete", trim_size="6x9")

    def test_generate_rate_limit(self):
        goal = self._create_goal(status="completed", title="Launch a Startup While Mastering Core Business Skills")
        self._create_book(
            goal=goal,
            status_value=JourneyBook.STATUS_QUEUED,
            with_pdf=False,
        )

        url = reverse("journeybook:journeybook-list")
        payload = {"goal_id": str(goal.id), "book_type": "in_progress"}
        response = self.client.post(url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(
            response.json().get("error"),
            'A Journey Book for "Launch a Startup While Mastering Core Business Skills" is already being generated.',
        )

    @patch("journeybook.views.JourneyBookViewSet._generate_sync")
    def test_generate_different_selection_not_rate_limited_by_recent_ready_book(self, mock_generate_sync):
        first_goal = self._create_goal(status="completed", title="Goal A")
        second_goal = self._create_goal(status="completed", title="Goal B")
        self._create_book(
            goal=first_goal,
            goals=[first_goal],
            status_value=JourneyBook.STATUS_READY,
            selection_mode="single",
            created_at=timezone.now() - timedelta(hours=1),
        )
        mock_generate_sync.return_value = None

        url = reverse("journeybook:journeybook-list")
        payload = {"goal_id": str(second_goal.id), "book_type": "complete"}
        response = self.client.post(url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_generate_same_all_goals_selection_is_rate_limited(self):
        first_goal = self._create_goal(status="completed", title="Goal A")
        second_goal = self._create_goal(status="completed", title="Goal B")
        self._create_book(
            goal=first_goal,
            goals=[first_goal, second_goal],
            status_value=JourneyBook.STATUS_READY,
            selection_mode="all",
            created_at=timezone.now() - timedelta(hours=1),
        )

        url = reverse("journeybook:journeybook-list")
        payload = {"include_all_goals": True, "book_type": "complete"}
        response = self.client.post(url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(
            response.json().get("error"),
            "You cannot generate an all-goals Journey Book more than once on the same day.",
        )
        self.assertIn("next_allowed_at", response.json())

    def test_download_requires_ownership(self):
        goal = self._create_goal(user=self.other_user, status="completed")
        book = self._create_book(user=self.other_user, goal=goal, with_pdf=True)

        self.client.force_authenticate(user=self.user)
        url = reverse("journeybook:journeybook-download", args=[str(book.id)])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_preview_non_failed_returns_400(self):
        goal = self._create_goal(status="in_progress")
        book = self._create_book(goal=goal, status_value=JourneyBook.STATUS_GENERATING)

        url = reverse("journeybook:journeybook-preview", args=[str(book.id)])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_preview_requires_ownership(self):
        goal = self._create_goal(user=self.other_user, status="completed")
        book = self._create_book(
            user=self.other_user,
            goal=goal,
            status_value=JourneyBook.STATUS_FAILED,
            error_message="ReportLab is required to build Journey Book PDFs.",
        )

        self.client.force_authenticate(user=self.user)
        url = reverse("journeybook:journeybook-preview", args=[str(book.id)])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_preview_returns_generated_chapter_snippets(self):
        goal = self._create_goal(status="completed")
        book = self._create_book(
            goal=goal,
            status_value=JourneyBook.STATUS_FAILED,
            error_message="ReportLab is required to build Journey Book PDFs.",
        )
        BookChapter.objects.create(
            journey_book=book,
            chapter_number=1,
            chapter_title="Who I Was",
            content="Generated chapter content " * 80,
            word_count=160,
            is_projection=False,
        )
        BookChapter.objects.create(
            journey_book=book,
            chapter_number=2,
            chapter_title="The Turning Point",
            content="Another generated chapter segment " * 60,
            word_count=120,
            is_projection=False,
        )

        url = reverse("journeybook:journeybook-preview", args=[str(book.id)])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertEqual(payload["source"], "generated_chapters")
        self.assertGreaterEqual(len(payload["sections"]), 2)
        self.assertIn("retry_context", payload)
        self.assertEqual(payload["retry_context"]["book_type"], book.book_type)

    def test_preview_returns_fallback_template_when_no_chapters(self):
        goal = self._create_goal(status="completed", start_days_ago=15)
        self._create_journal_entry(entry_date=date.today() - timedelta(days=2))
        self._create_journal_entry(entry_date=date.today() - timedelta(days=1))

        book = self._create_book(
            goal=goal,
            status_value=JourneyBook.STATUS_FAILED,
            error_message="ReportLab is required to build Journey Book PDFs.",
        )

        url = reverse("journeybook:journeybook-preview", args=[str(book.id)])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertEqual(payload["source"], "fallback_template")
        self.assertGreaterEqual(len(payload["sections"]), 1)
        self.assertIn("stats", payload)
        self.assertIn("days_of_data", payload["stats"])

    @patch("journeybook.views.JourneyBookViewSet._collect_preview_metrics", side_effect=ValueError("metrics failure"))
    def test_preview_metrics_value_error_returns_safe_fallback(self, _mock_collect):
        goal = self._create_goal(status="completed", start_days_ago=15)
        book = self._create_book(
            goal=goal,
            status_value=JourneyBook.STATUS_FAILED,
            error_message="ReportLab is required to build Journey Book PDFs.",
        )

        url = reverse("journeybook:journeybook-preview", args=[str(book.id)])
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertEqual(payload["source"], "fallback_template")
        self.assertGreaterEqual(len(payload["sections"]), 1)

    def test_failed_serializer_exposes_error_mapping_and_retry_context(self):
        goal = self._create_goal(status="completed")
        book = self._create_book(
            goal=goal,
            status_value=JourneyBook.STATUS_FAILED,
            error_message="ReportLab is required to build Journey Book PDFs.",
        )
        book.metadata = {
            "generation_source": {
                "overall": "mixed",
                "chapters": "ai",
                "motivational_pages": "fallback",
                "counts": {
                    "chapters_ai": 2,
                    "chapters_fallback": 0,
                    "motivational_ai": 0,
                    "motivational_fallback": 1,
                },
            },
            "asset_generation_warnings": [{"asset_key": "heatmap", "severity": "required", "error": "RuntimeError"}],
            "content_stats": {
                "chapter_count": 2,
                "motivational_page_count": 1,
                "word_count": 420,
                "page_count": 17,
            },
        }
        book.save(update_fields=["metadata"])

        url = reverse("journeybook:journeybook-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        record = payload["results"][0] if isinstance(payload, dict) else payload[0]
        self.assertEqual(record["error_code"], "pdf_dependency_missing")
        self.assertTrue(record["can_preview_sample"])
        self.assertTrue(record["can_retry"])
        self.assertIn("retry_context", record)
        self.assertIn("error_display", record)
        self.assertEqual(record["generation_source"]["counts"]["motivational_fallback"], 1)
        self.assertEqual(record["asset_generation"]["status"], "degraded")
        self.assertEqual(record["content_stats"]["word_count"], 420)

    def test_serializer_exposes_multi_goal_selection_metadata(self):
        first_goal = self._create_goal(status="completed", title="Goal 1")
        second_goal = self._create_goal(status="in_progress", title="Goal 2")
        self._create_book(
            goal=first_goal,
            goals=[first_goal, second_goal],
            selection_mode="multiple",
        )

        url = reverse("journeybook:journeybook-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        record = payload["results"][0] if isinstance(payload, dict) else payload[0]
        self.assertEqual(record["selection_mode"], "multiple")
        self.assertEqual(record["goal_titles"], ["Goal 1", "Goal 2"])
        self.assertEqual(record["retry_context"]["goal_ids"], [str(first_goal.id), str(second_goal.id)])

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

    @patch(
        "journeybook.models.JourneyBook.pdf_file.field.storage.open",
        side_effect=FileNotFoundError("missing file"),
    )
    def test_download_missing_storage_file_returns_structured_error(self, _mock_open):
        goal = self._create_goal(status="completed")
        book = self._create_book(goal=goal, with_pdf=True, status_value=JourneyBook.STATUS_READY)

        url = reverse("journeybook:journeybook-download", args=[str(book.id)])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        payload = response.json()
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error_type"], "STORAGE_ERROR")
        self.assertIn("fallback_available", payload)

    @patch(
        "journeybook.services.pdf_builder.PDFBuilder.build",
        return_value=BytesIO(b"%PDF-1.4\nreal-export\n%%EOF"),
    )
    def test_export_ready_returns_real_pdf_payload(self, _mock_pdf):
        goal = self._create_goal(status="completed")
        book = self._create_book(goal=goal, status_value=JourneyBook.STATUS_READY, with_pdf=False)
        BookChapter.objects.create(
            journey_book=book,
            chapter_number=1,
            chapter_title="Chapter One",
            content="Generated chapter content " * 20,
            word_count=80,
            is_projection=False,
        )
        book.metadata = {
            "chapter_count": 1,
            "page_count": 10,
            "word_count": 80,
            "motivational_pages": [
                {"page_type": "letter_to_past_self", "content": "Persisted motivational text.", "content_source": "ai"}
            ],
        }
        book.save(update_fields=["metadata"])

        url = reverse("journeybook:journeybook-export", args=[str(book.id)])
        response = self.client.post(url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertFalse(payload["is_demo_pdf"])
        self.assertIn("pdf_url", payload)
        self.assertIsNone(payload["error_type"])
        self.assertEqual(payload["asset_generation"]["status"], "complete")
        book.refresh_from_db()
        self.assertTrue(bool(book.pdf_file))

    @patch(
        "journeybook.services.pdf_builder.PDFBuilder.build",
        return_value=BytesIO(b"%PDF-1.4\nreal-export\n%%EOF"),
    )
    def test_export_reuses_stored_motivational_pages(self, mock_pdf):
        goal = self._create_goal(status="completed")
        book = self._create_book(goal=goal, status_value=JourneyBook.STATUS_READY, with_pdf=False)
        BookChapter.objects.create(
            journey_book=book,
            chapter_number=1,
            chapter_title="Chapter One",
            content="Generated chapter content " * 20,
            word_count=80,
            is_projection=False,
        )
        book.metadata = {
            "motivational_pages": [
                {"page_type": "letter_to_past_self", "content": "Stored motivation one.", "content_source": "ai"},
                {"page_type": "streak_heatmap", "content": "Stored motivation two.", "content_source": "fallback"},
            ]
        }
        book.save(update_fields=["metadata"])

        response = self.client.post(reverse("journeybook:journeybook-export", args=[str(book.id)]), {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        pdf_args = mock_pdf.call_args.args
        self.assertEqual(pdf_args[2], ["Stored motivation one.", "Stored motivation two."])

    @patch(
        "journeybook.services.pdf_builder.PDFBuilder.build",
        return_value=BytesIO(b"%PDF-1.4\ndemo-export\n%%EOF"),
    )
    def test_export_failed_returns_demo_pdf_payload(self, _mock_pdf):
        goal = self._create_goal(status="completed")
        book = self._create_book(
            goal=goal,
            status_value=JourneyBook.STATUS_FAILED,
            with_pdf=False,
            error_message="Generation failed for testing.",
        )

        url = reverse("journeybook:journeybook-export", args=[str(book.id)])
        response = self.client.post(url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertTrue(payload["is_demo_pdf"])
        self.assertIn("pdf_url", payload)
        self.assertIn(payload["error_type"], ["GENERATION_FAILED", "INSUFFICIENT_DATA", "EMPTY_CONTENT"])
        book.refresh_from_db()
        self.assertTrue(bool(book.pdf_file))

    @patch(
        "journeybook.services.pdf_builder.PDFBuilder.build",
        return_value=BytesIO(b"%PDF-1.4\ndemo-insufficient\n%%EOF"),
    )
    def test_export_insufficient_data_returns_demo_pdf(self, _mock_pdf):
        goal = self._create_goal(status="not_started", start_days_ago=0)
        book = JourneyBook.objects.create(
            user=self.user,
            goal=goal,
            book_type=JourneyBook.BOOK_TYPE_IN_PROGRESS,
            status=JourneyBook.STATUS_FAILED,
            data_start_date=date.today(),
            data_end_date=date.today(),
            days_of_data=1,
            error_message="Come back after at least 7 days of journey data.",
        )

        url = reverse("journeybook:journeybook-export", args=[str(book.id)])
        response = self.client.post(url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertTrue(payload["is_demo_pdf"])
        self.assertEqual(payload["error_type"], "INSUFFICIENT_DATA")
        self.assertIsNotNone(payload["demo_pdf_url"])
        book.refresh_from_db()
        self.assertTrue(bool(book.pdf_file))

    @patch(
        "journeybook.views.JourneyBookViewSet._build_and_store_demo_pdf",
        side_effect=RuntimeError("demo fallback unavailable"),
    )
    @patch(
        "journeybook.views.JourneyBookViewSet._build_and_store_real_pdf",
        side_effect=RuntimeError("pdf engine crashed"),
    )
    def test_export_pdf_engine_failure_returns_structured_error_with_fallback(
        self,
        _mock_real,
        _mock_demo,
    ):
        goal = self._create_goal(status="completed")
        book = self._create_book(goal=goal, status_value=JourneyBook.STATUS_READY, with_pdf=False)
        book.metadata = {"chapter_count": 2, "page_count": 12, "word_count": 500}
        book.save(update_fields=["metadata"])

        url = reverse("journeybook:journeybook-export", args=[str(book.id)])
        response = self.client.post(url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error_type"], "PDF_ENGINE_ERROR")
        self.assertTrue(payload["fallback_available"])
        self.assertFalse(payload["is_demo_pdf"])

    @patch("journeybook.views.JourneyBookViewSet._build_and_store_demo_pdf")
    @patch(
        "journeybook.views.JourneyBookViewSet._build_and_store_real_pdf",
        side_effect=RuntimeError("pdf engine crashed"),
    )
    def test_export_real_pdf_runtime_failure_falls_back_to_demo(self, _mock_real, _mock_demo):
        goal = self._create_goal(status="completed")
        book = self._create_book(goal=goal, status_value=JourneyBook.STATUS_READY, with_pdf=False)
        book.metadata = {"chapter_count": 2, "page_count": 12, "word_count": 500}
        book.save(update_fields=["metadata"])

        url = reverse("journeybook:journeybook-export", args=[str(book.id)])
        response = self.client.post(url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertTrue(payload["is_demo_pdf"])
        self.assertEqual(payload["error_type"], "PDF_ENGINE_ERROR")
        self.assertFalse(payload["fallback_available"])
        _mock_demo.assert_called_once()

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

    def test_metrics_calculator_does_not_persist_derived_milestones(self):
        entry_day = date.today() - timedelta(days=1)
        result = MetricsCalculator(
            {
                "user": self.user,
                "journals": [
                    {
                        "entry_date": entry_day,
                        "reflection_raw": "Persistence owner should be generation, not calculation.",
                        "struggle_raw": "Still enough detail.",
                        "sentiment_score": 0.3,
                        "total_word_count": 90,
                    }
                ],
                "streaks": {"longest_streak": 7, "last_entry_date": entry_day},
            }
        ).calculate_all()
        self.assertTrue(result["derived_milestones"])
        self.assertEqual(DerivedMilestone.objects.filter(user=self.user).count(), 0)

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
    @patch("journeybook.services.ai_generator.AIGenerator.generate_motivational_page_result")
    @patch("journeybook.services.ai_generator.AIGenerator.generate_chapter_result")
    def test_book_chapter_saved_per_chapter(
        self,
        mock_chapter,
        mock_motivational,
        _mock_completion,
        _mock_sentiment,
        _mock_streak,
        _mock_heatmap,
        _mock_timeline,
        _mock_pdf,
    ):
        mock_chapter.return_value = MagicMock(
            content="Generated chapter text " * 50,
            to_metadata=lambda: {
                "content": "Generated chapter text " * 50,
                "content_source": "ai",
                "provider": "ollama",
                "model": "journeybook-test",
                "error_summary": None,
            },
        )
        mock_motivational.return_value = MagicMock(
            content="Motivational page text for testing.",
            to_metadata=lambda: {
                "content": "Motivational page text for testing.",
                "content_source": "fallback",
                "provider": "ollama",
                "model": "journeybook-test",
                "error_summary": "provider_not_configured",
            },
        )
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
        self.assertEqual(book.metadata["generation_source"]["counts"]["chapters_ai"], 5)
        self.assertEqual(book.metadata["generation_source"]["counts"]["motivational_fallback"], 5)
        self.assertEqual(len(book.metadata["motivational_pages"]), 5)
        self.assertEqual(book.metadata["content_stats"]["chapter_count"], 5)

    def test_is_empty_content_recomputes_stats_instead_of_trusting_stale_metadata(self):
        goal = self._create_goal(status="completed")
        book = self._create_book(goal=goal, status_value=JourneyBook.STATUS_READY, with_pdf=False)
        book.metadata = {"chapter_count": 3, "page_count": 20, "word_count": 600}
        book.save(update_fields=["metadata"])
        BookChapter.objects.create(
            journey_book=book,
            chapter_number=1,
            chapter_title="Empty chapter",
            content="",
            word_count=0,
            is_projection=False,
        )

        response = self.client.post(reverse("journeybook:journeybook-export", args=[str(book.id)]), {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertTrue(payload["is_demo_pdf"])
        self.assertEqual(payload["error_type"], "EMPTY_CONTENT")
        book.refresh_from_db()
        self.assertEqual(book.metadata["content_stats"]["chapter_count"], 0)
        self.assertEqual(book.metadata["content_stats"]["word_count"], 0)

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
        side_effect=RuntimeError("heatmap failed"),
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
    @patch("journeybook.services.ai_generator.AIGenerator.generate_motivational_page_result")
    @patch("journeybook.services.ai_generator.AIGenerator.generate_chapter_result")
    def test_generation_records_chart_failure_warnings_while_staying_ready(
        self,
        mock_chapter,
        mock_motivational,
        _mock_completion,
        _mock_sentiment,
        _mock_streak,
        _mock_heatmap,
        _mock_timeline,
        _mock_pdf,
    ):
        mock_chapter.return_value = MagicMock(
            content="Generated chapter text " * 50,
            to_metadata=lambda: {
                "content": "Generated chapter text " * 50,
                "content_source": "ai",
                "provider": "ollama",
                "model": "journeybook-test",
                "error_summary": None,
            },
        )
        mock_motivational.return_value = MagicMock(
            content="Motivational page text for testing.",
            to_metadata=lambda: {
                "content": "Motivational page text for testing.",
                "content_source": "ai",
                "provider": "ollama",
                "model": "journeybook-test",
                "error_summary": None,
            },
        )

        response = self.client.post(
            reverse("journeybook:journeybook-list"),
            {"goal_id": str(self._create_goal(status='completed').id), "book_type": "in_progress"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        book = JourneyBook.objects.latest("created_at")
        self.assertEqual(book.status, JourneyBook.STATUS_READY)
        self.assertEqual(book.metadata["asset_generation_warnings"][0]["asset_key"], "heatmap")
        response_payload = response.json()
        self.assertEqual(response_payload["asset_generation"]["status"], "degraded")
        self.assertEqual(response_payload["asset_generation"]["warnings"][0]["asset_key"], "heatmap")

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
    @patch("journeybook.services.ai_generator.AIGenerator.generate_motivational_page_result")
    @patch("journeybook.services.ai_generator.AIGenerator.generate_chapter_result")
    def test_generation_persists_derived_milestones_once(
        self,
        mock_chapter,
        mock_motivational,
        _mock_completion,
        _mock_sentiment,
        _mock_streak,
        _mock_heatmap,
        _mock_timeline,
        _mock_pdf,
    ):
        mock_chapter.return_value = MagicMock(
            content="Generated chapter text " * 50,
            to_metadata=lambda: {
                "content": "Generated chapter text " * 50,
                "content_source": "ai",
                "provider": "ollama",
                "model": "journeybook-test",
                "error_summary": None,
            },
        )
        mock_motivational.return_value = MagicMock(
            content="Motivational page text for testing.",
            to_metadata=lambda: {
                "content": "Motivational page text for testing.",
                "content_source": "ai",
                "provider": "ollama",
                "model": "journeybook-test",
                "error_summary": None,
            },
        )
        goal = self._create_goal(status="completed")
        journal_day = date.today() - timedelta(days=1)
        self._create_journal_entry(entry_date=journal_day, reflection_raw="Detailed enough to derive milestones.")

        response = self.client.post(
            reverse("journeybook:journeybook-list"),
            {"goal_id": str(goal.id), "book_type": "in_progress"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        milestones = list(DerivedMilestone.objects.filter(user=self.user))
        trigger_types = [milestone.trigger_type for milestone in milestones]
        self.assertEqual(len(trigger_types), len(set(trigger_types)))

    def test_pdf_builder_respects_trim_page_size(self):
        builder = PDFBuilder(
            user_data={
                "profile": {"name": "Test User"},
                "goal": {"title": "Test Goal", "status": "in_progress", "deadline": date.today()},
            },
            metrics={
                "journey_overview": {
                    "start_date": date.today() - timedelta(days=30),
                    "end_date": date.today(),
                    "total_entries": 30,
                },
                "derived_milestones": [],
            },
            book_type=JourneyBook.BOOK_TYPE_COMPLETE,
            trim_size="5.5x8.5",
        )
        page_width, page_height = builder.get_page_size_points()
        self.assertAlmostEqual(page_width, 396.0, delta=0.1)
        self.assertAlmostEqual(page_height, 612.0, delta=0.1)

    def test_pdf_builder_fixed_image_frame_uses_trim_spec(self):
        builder = PDFBuilder(
            user_data={},
            metrics={},
            book_type=JourneyBook.BOOK_TYPE_IN_PROGRESS,
            trim_size="7x10",
        )
        expected_width, expected_height = builder.get_image_frame_size_points()
        self.assertAlmostEqual(expected_width, 388.8, delta=0.1)
        self.assertAlmostEqual(expected_height, 223.2, delta=0.1)

        # 2000x1000 image should fit exactly to frame width and preserve ratio.
        fit_width, fit_height = builder._fit_within_frame(
            src_width=2000.0,
            src_height=1000.0,
            frame_width=expected_width,
            frame_height=expected_height,
        )
        self.assertAlmostEqual(fit_width, expected_width, delta=0.1)
        self.assertAlmostEqual(fit_height, expected_width / 2.0, delta=0.1)
