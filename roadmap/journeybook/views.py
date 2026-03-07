from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any

from django.core.files.base import ContentFile
from django.core.exceptions import ImproperlyConfigured, ObjectDoesNotExist
from django.http import FileResponse, HttpResponse, JsonResponse
from django.urls import reverse
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.renderers import BaseRenderer, JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet

from ai.config import get_journeybook_model
from journeybook.models import BookAsset, BookChapter, DerivedMilestone, JourneyBook
from journeybook.serializers import (
    BookEligibilitySerializer,
    JourneyBookGenerateSerializer,
    JourneyBookSerializer,
)
from journeybook.services.ai_generator import AIGenerator, ChapterFallbacks
from journeybook.services.data_collector import DataCollector
from journeybook.services.demo_mode import build_demo_book_payload, build_demo_pdf_bytes
from journeybook.services.image_generator import ImageGenerator
from journeybook.services.metrics_calculator import MetricsCalculator
from journeybook.services.pdf_builder import PDFBuilder

logger = logging.getLogger(__name__)


class PDFBinaryRenderer(BaseRenderer):
    media_type = "application/pdf"
    format = "pdf"
    charset = None
    render_style = "binary"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data


class JourneyBookViewSet(ModelViewSet):
    ERROR_TYPE_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    ERROR_TYPE_GENERATION_FAILED = "GENERATION_FAILED"
    ERROR_TYPE_EMPTY_CONTENT = "EMPTY_CONTENT"
    ERROR_TYPE_PDF_ENGINE_ERROR = "PDF_ENGINE_ERROR"
    ERROR_TYPE_STORAGE_ERROR = "STORAGE_ERROR"

    permission_classes = [IsAuthenticated]
    serializer_class = JourneyBookSerializer

    def get_queryset(self):
        return JourneyBook.objects.filter(user=self.request.user).order_by("-created_at")

    def get_serializer_class(self):
        if self.action == "create":
            return JourneyBookGenerateSerializer
        return JourneyBookSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data
        mode = validated.get("mode", "real")

        if mode == "demo":
            payload = self._build_demo_json_payload(
                book_type=validated["book_type"],
                trim_size=validated.get("trim_size"),
            )
            return Response(payload, status=status.HTTP_200_OK)

        selected_goals = validated.get("selected_goals") or []
        representative_goal = validated.get("representative_goal")
        selection_mode = validated.get("selection_mode", "overall")
        privacy_settings = validated.get("privacy_settings") or {}
        collector = DataCollector(
            user=request.user,
            selected_goals=selected_goals,
            selection_mode=selection_mode,
            privacy_settings=privacy_settings,
        )
        collected_data = collector.collect_all_data()
        eligibility = validated.get("eligibility") or collector.check_eligibility()

        metrics_calculator = MetricsCalculator(collected_data)
        metrics = metrics_calculator.calculate_all()
        metrics["profile"] = collected_data.get("profile") or {}
        metrics["streaks"] = collected_data.get("streaks") or {}
        metrics["goal"] = collected_data.get("goal") or {}
        metrics["word_frequencies"] = collected_data.get("word_frequencies") or {}

        start_date = metrics.get("journey_overview", {}).get("start_date") or (
            collected_data.get("goal", {}).get("start_date")
            or collected_data.get("goal", {}).get("created_at")
            or date.today()
        )
        end_date = metrics.get("journey_overview", {}).get("end_date") or date.today()

        book = JourneyBook.objects.create(
            user=request.user,
            goal=representative_goal,
            book_type=validated["book_type"],
            status=JourneyBook.STATUS_QUEUED,
            data_start_date=start_date,
            data_end_date=end_date,
            days_of_data=int(eligibility.get("days_of_data") or 0),
            privacy_settings=privacy_settings,
            metadata={
                "selection_mode": selection_mode,
                "goal_ids": [str(goal.id) for goal in selected_goals],
                "goal_titles": [goal.title for goal in selected_goals],
            },
        )
        if selected_goals:
            book.goals.set(selected_goals)

        try:
            self._generate_sync(book=book, data=collected_data, metrics=metrics)
        except (ImproperlyConfigured, RuntimeError, ValueError, OSError, ObjectDoesNotExist) as exc:
            logger.exception("JourneyBook sync generation failed for book %s: %s", book.id, exc)

        output = JourneyBookSerializer(book, context={"request": request})
        return Response(output.data, status=status.HTTP_201_CREATED)

    @action(
        detail=False,
        methods=["get"],
        permission_classes=[AllowAny],
        authentication_classes=[],
        url_path="demo-preview",
    )
    def demo_preview(self, request):
        book_type = request.query_params.get("book_type", JourneyBook.BOOK_TYPE_COMPLETE)
        trim_size = request.query_params.get("trim_size")
        if book_type not in {JourneyBook.BOOK_TYPE_COMPLETE, JourneyBook.BOOK_TYPE_IN_PROGRESS}:
            book_type = JourneyBook.BOOK_TYPE_COMPLETE
        payload = self._build_demo_json_payload(book_type=book_type, trim_size=trim_size)
        return Response(payload, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        book = self.get_object()
        if book.pdf_file:
            book.pdf_file.delete(save=False)
        book.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["get"])
    def eligibility(self, request):
        normalized = JourneyBookGenerateSerializer.normalize_goal_selection(
            user=request.user,
            goal_id=request.query_params.get("goal_id"),
            goal_ids=request.query_params.getlist("goal_ids"),
            include_all_goals=str(request.query_params.get("include_all_goals", "")).lower() in {"1", "true", "yes"},
        )
        collector = DataCollector(
            request.user,
            selected_goals=normalized["selected_goals"],
            selection_mode=normalized["selection_mode"],
        )
        eligibility = collector.check_eligibility()
        serializer = BookEligibilitySerializer(instance=eligibility)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        book = self.get_object()
        if not book.pdf_file:
            return Response({"error": "Book not ready"}, status=status.HTTP_404_NOT_FOUND)
        try:
            response = FileResponse(book.pdf_file.open("rb"), content_type="application/pdf")
        except (FileNotFoundError, OSError, ValueError):
            return Response(
                self._export_error_payload(
                    error_type=self.ERROR_TYPE_STORAGE_ERROR,
                    fallback_available=book.status == JourneyBook.STATUS_FAILED,
                ),
                status=status.HTTP_404_NOT_FOUND,
            )
        response["Content-Disposition"] = (
            f'attachment; filename="journey_book_{str(book.id)[:8]}.pdf"'
        )
        return response

    @action(detail=True, methods=["post"])
    def export(self, request, pk=None):
        book = self.get_object()
        force_demo = str(request.query_params.get("force_demo", "")).lower() in {"1", "true", "yes"}

        should_export_demo = force_demo or self._should_export_demo(book)
        error_type = self._error_type_for_book(book)

        if not should_export_demo and book.status == JourneyBook.STATUS_READY and book.pdf_file:
            return Response(
                self._export_response_payload(
                    request=request,
                    book=book,
                    is_demo_pdf=False,
                    error_type=None,
                    fallback_available=True,
                ),
                status=status.HTTP_200_OK,
            )

        if should_export_demo:
            try:
                self._build_and_store_demo_pdf(book)
                return Response(
                    self._export_response_payload(
                        request=request,
                        book=book,
                        is_demo_pdf=True,
                        error_type=error_type,
                        fallback_available=False,
                    ),
                    status=status.HTTP_200_OK,
                )
            except RuntimeError:
                return Response(
                    self._export_error_payload(
                        error_type=self.ERROR_TYPE_PDF_ENGINE_ERROR,
                        fallback_available=False,
                    ),
                    status=status.HTTP_200_OK,
                )
            except (OSError, ValueError):
                return Response(
                    self._export_error_payload(
                        error_type=self.ERROR_TYPE_STORAGE_ERROR,
                        fallback_available=False,
                    ),
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        try:
            self._build_and_store_real_pdf(book)
            return Response(
                self._export_response_payload(
                    request=request,
                    book=book,
                    is_demo_pdf=False,
                    error_type=None,
                    fallback_available=True,
                ),
                status=status.HTTP_200_OK,
            )
        except RuntimeError:
            # Real export failed due to PDF runtime dependency, try demo fallback.
            try:
                self._build_and_store_demo_pdf(book)
                return Response(
                    self._export_response_payload(
                        request=request,
                        book=book,
                        is_demo_pdf=True,
                        error_type=self.ERROR_TYPE_PDF_ENGINE_ERROR,
                        fallback_available=False,
                    ),
                    status=status.HTTP_200_OK,
                )
            except (RuntimeError, OSError, ValueError):
                return Response(
                    self._export_error_payload(
                        error_type=self.ERROR_TYPE_PDF_ENGINE_ERROR,
                        fallback_available=True,
                    ),
                    status=status.HTTP_200_OK,
                )
        except (OSError, ValueError):
            # Storage/runtime write failed, attempt demo fallback before returning hard error.
            try:
                self._build_and_store_demo_pdf(book)
                return Response(
                    self._export_response_payload(
                        request=request,
                        book=book,
                        is_demo_pdf=True,
                        error_type=self.ERROR_TYPE_STORAGE_ERROR,
                        fallback_available=False,
                    ),
                    status=status.HTTP_200_OK,
                )
            except (RuntimeError, OSError, ValueError):
                return Response(
                    self._export_error_payload(
                        error_type=self.ERROR_TYPE_STORAGE_ERROR,
                        fallback_available=True,
                    ),
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        book = self.get_object()
        if book.status != JourneyBook.STATUS_FAILED:
            return Response(
                {"error": "Preview is available only for failed Journey Books."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        payload = self._build_preview_payload(book)
        return Response(payload, status=status.HTTP_200_OK)

    def _generate_sync(self, book: JourneyBook, data: dict, metrics: dict) -> None:
        book.mark_generating()
        try:
            ai_gen = AIGenerator()
            img_gen = ImageGenerator(metrics)
            structure = self._get_structure(book.book_type)

            chapters_text: list[str] = []
            ai_model_used = get_journeybook_model()

            for idx, chapter in enumerate(structure["chapters"], start=1):
                start = time.time()
                text = ai_gen.generate_chapter(chapter, metrics, book.book_type)
                duration = time.time() - start
                BookChapter.objects.create(
                    journey_book=book,
                    chapter_number=idx,
                    chapter_title=chapter["title"],
                    content=text,
                    word_count=len((text or "").split()),
                    is_projection=bool(chapter.get("is_projection", False)),
                    ai_model_used=ai_model_used,
                    generation_time_seconds=duration,
                )
                chapters_text.append(text)

            motivational_text: list[str] = []
            for page_type in structure["motivational_pages"]:
                page_text = ai_gen.generate_motivational_page(page_type, metrics)
                motivational_text.append(page_text)

            images: dict[str, object] = {}
            try:
                images["completion"] = img_gen.generate_completion_chart()
                images["sentiment"] = img_gen.generate_sentiment_chart()
                images["streak"] = img_gen.generate_streak_chart()
                images["heatmap"] = img_gen.generate_heatmap()
                frequencies = data.get("word_frequencies") or {}
                if frequencies:
                    images["wordcloud"] = img_gen.generate_wordcloud(frequencies)
                images["milestone"] = img_gen.generate_milestone_timeline(
                    metrics.get("derived_milestones") or []
                )
            except (RuntimeError, ValueError, OSError) as exc:
                logger.warning("JourneyBook chart generation failed for book %s: %s", book.id, exc)

            pdf_builder = PDFBuilder(data, metrics, book.book_type)
            pdf_bytes = pdf_builder.build(chapters_text, motivational_text, images)
            filename = f"journey_book_{book.user_id}_{book.id}.pdf"
            book.pdf_file.save(filename, ContentFile(pdf_bytes.getvalue()), save=False)
            book.save(update_fields=["pdf_file"])

            asset_type_mapping = {
                "completion": BookAsset.ASSET_TYPE_COMPLETION_CHART,
                "sentiment": BookAsset.ASSET_TYPE_SENTIMENT_CHART,
                "streak": BookAsset.ASSET_TYPE_STREAK_CHART,
                "heatmap": BookAsset.ASSET_TYPE_HEATMAP,
                "wordcloud": BookAsset.ASSET_TYPE_WORDCLOUD,
                "milestone": BookAsset.ASSET_TYPE_MILESTONE_TIMELINE,
            }
            for key, value in images.items():
                if value is None:
                    continue
                BookAsset.objects.create(
                    journey_book=book,
                    asset_type=asset_type_mapping[key],
                    file_path=f"in_memory://{book.id}/{key}.png",
                )

            for milestone in metrics.get("derived_milestones") or []:
                DerivedMilestone.objects.get_or_create(
                    user=book.user,
                    trigger_type=milestone["trigger_type"],
                    defaults={
                        "label": milestone["label"],
                        "achieved_date": milestone["achieved_date"],
                        "category": milestone.get("category", "personal"),
                    },
                )

            page_count = (len(chapters_text) * 5) + (len(motivational_text) * 2) + 5
            chapter_count = len(chapters_text)
            word_count = sum(len((text or "").split()) for text in chapters_text)
            metadata = {
                "page_count": page_count,
                "chapter_count": chapter_count,
                "word_count": word_count,
                "images_generated": len(images),
            }
            book.mark_ready(metadata=metadata)
        except (ImproperlyConfigured, RuntimeError, ValueError, OSError, ObjectDoesNotExist) as exc:
            book.mark_failed(str(exc))
            raise

    def _build_and_store_real_pdf(self, book: JourneyBook) -> None:
        chapters = list(book.chapters.order_by("chapter_number"))
        if not chapters:
            raise RuntimeError("No generated chapter content is available for export.")

        try:
            collected_data, metrics = self._collect_preview_metrics(book)
        except (RuntimeError, ValueError, OSError, ObjectDoesNotExist):
            collected_data = {"profile": {"name": str(book.user.email)}, "goal": {}}
            metrics = {"journey_overview": {"start_date": book.data_start_date, "end_date": book.data_end_date}}

        chapter_texts = [chapter.content for chapter in chapters]
        motivational_pages = self._demo_motivational_pages()
        pdf_builder = PDFBuilder(collected_data, metrics, book.book_type)
        pdf_bytes = pdf_builder.build(chapter_texts, motivational_pages, {})
        filename = f"journey_book_{book.user_id}_{book.id}_export.pdf"
        book.pdf_file.save(filename, ContentFile(pdf_bytes.getvalue()), save=False)
        metadata = dict(book.metadata or {})
        metadata["last_export_is_demo"] = False
        book.metadata = metadata
        book.save(update_fields=["pdf_file", "metadata", "updated_at"])

    def _build_and_store_demo_pdf(self, book: JourneyBook) -> None:
        demo_data, demo_metrics = self._demo_seed_payload(book)
        chapter_texts = self._demo_chapters(book)
        motivational_pages = self._demo_motivational_pages()
        pdf_builder = PDFBuilder(demo_data, demo_metrics, JourneyBook.BOOK_TYPE_COMPLETE)
        pdf_bytes = pdf_builder.build(chapter_texts, motivational_pages, {})
        filename = f"journey_book_{book.user_id}_{book.id}_demo_export.pdf"
        book.pdf_file.save(filename, ContentFile(pdf_bytes.getvalue()), save=False)
        metadata = dict(book.metadata or {})
        metadata["last_export_is_demo"] = True
        book.metadata = metadata
        book.save(update_fields=["pdf_file", "metadata", "updated_at"])

    def _export_response_payload(
        self,
        request,
        book: JourneyBook,
        is_demo_pdf: bool,
        error_type: str | None,
        fallback_available: bool,
    ) -> dict[str, Any]:
        download_url = request.build_absolute_uri(
            reverse("journeybook:journeybook-download", args=[book.id])
        )
        return {
            "status": "success",
            "pdf_url": download_url,
            "demo_pdf_url": download_url if is_demo_pdf else None,
            "is_demo_pdf": is_demo_pdf,
            "error_type": error_type,
            "fallback_available": fallback_available,
        }

    @staticmethod
    def _export_error_payload(error_type: str, fallback_available: bool) -> dict[str, Any]:
        return {
            "status": "error",
            "pdf_url": None,
            "demo_pdf_url": None,
            "is_demo_pdf": False,
            "error_type": error_type,
            "fallback_available": fallback_available,
        }

    def _should_export_demo(self, book: JourneyBook) -> bool:
        if book.status == JourneyBook.STATUS_FAILED:
            return True
        if book.status == JourneyBook.STATUS_READY and self._is_empty_content(book):
            return True
        return False

    def _is_empty_content(self, book: JourneyBook) -> bool:
        metadata = book.metadata or {}
        chapter_count = int(metadata.get("chapter_count") or 0)
        page_count = int(metadata.get("page_count") or 0)
        word_count = int(metadata.get("word_count") or 0)
        return chapter_count <= 0 or page_count <= 0 or word_count <= 0

    def _error_type_for_book(self, book: JourneyBook) -> str | None:
        raw_error = (book.error_message or "").strip().lower()
        if book.days_of_data < 7 or "at least 7 days" in raw_error or "insufficient" in raw_error:
            return self.ERROR_TYPE_INSUFFICIENT_DATA
        if self._is_empty_content(book):
            return self.ERROR_TYPE_EMPTY_CONTENT
        if book.status == JourneyBook.STATUS_FAILED:
            return self.ERROR_TYPE_GENERATION_FAILED
        return None

    def _demo_seed_payload(self, book: JourneyBook) -> tuple[dict[str, Any], dict[str, Any]]:
        goal_titles = list(book.goals.all().values_list("title", flat=True))
        if book.goal_id and book.goal and not goal_titles:
            goal_titles = [book.goal.title]
        goal_title = goal_titles[0] if len(goal_titles) == 1 else ("All goals" if self._selection_mode(book) == "all" else "your journey")
        profile_name = getattr(book.user, "username", "") or getattr(book.user, "email", "") or "DayOneGoal Member"
        data = {
            "profile": {"name": profile_name, "email": getattr(book.user, "email", "")},
            "goal": {"title": goal_title, "status": "in_progress", "deadline": book.data_end_date},
        }
        metrics = {
            "journey_overview": {
                "start_date": book.data_start_date,
                "end_date": book.data_end_date,
            },
            "derived_milestones": [],
        }
        return data, metrics

    def _demo_chapters(self, book: JourneyBook) -> list[str]:
        _, metrics = self._demo_seed_payload(book)
        structure = self._get_structure(JourneyBook.BOOK_TYPE_COMPLETE)
        chapters: list[str] = []
        for chapter in structure["chapters"]:
            chapter_id = chapter.get("id", "ch1")
            chapters.append(ChapterFallbacks.get(chapter_id, metrics, JourneyBook.BOOK_TYPE_COMPLETE))
        return chapters

    @staticmethod
    def _demo_motivational_pages() -> list[str]:
        return [
            "This demo page shows the print layout and narrative flow of your Journey Book.",
            "Add more journal entries and completed routines to unlock your full personalized edition.",
            "Consistency creates momentum. Keep showing up, and your real story will grow richer.",
        ]

    def _build_preview_payload(self, book: JourneyBook) -> dict[str, Any]:
        payload = {
            "book_id": str(book.id),
            "book_type": book.book_type,
            "title": self._preview_title(book),
            "subtitle": self._preview_subtitle(book),
            "disclaimer": (
                "Sample preview based on your journey data. Final PDF generation is unavailable right now."
            ),
            "retry_context": self._retry_context(book),
        }

        chapter_sections = self._preview_sections_from_chapters(book)
        if chapter_sections:
            return {
                **payload,
                "source": "generated_chapters",
                "sections": chapter_sections,
                "stats": self._preview_stats_best_effort(book),
            }

        try:
            _, metrics = self._collect_preview_metrics(book)
            fallback_sections = self._preview_sections_from_fallback(book, metrics)
            return {
                **payload,
                "source": "fallback_template",
                "sections": fallback_sections,
                "stats": self._preview_stats(book, metrics=metrics),
            }
        except (RuntimeError, ValueError, OSError, ObjectDoesNotExist):
            return {
                **payload,
                "source": "fallback_template",
                "sections": [
                    {
                        "chapter_number": 1,
                        "chapter_title": "A Glimpse of Your Story",
                        "excerpt": (
                            "This sample shows the narrative style your Journey Book uses. "
                            "Once generation is available again, your complete personalized book "
                            "will include your milestones, reflections, and progress arc."
                        ),
                        "is_projection": False,
                    }
                ],
                "stats": self._preview_stats(book),
            }

    def _collect_preview_metrics(self, book: JourneyBook) -> tuple[dict[str, Any], dict[str, Any]]:
        selected_goals = list(book.goals.all())
        if not selected_goals and book.goal_id and book.goal:
            selected_goals = [book.goal]
        collector = DataCollector(
            user=book.user,
            selected_goals=selected_goals,
            selection_mode=self._selection_mode(book),
            privacy_settings=book.privacy_settings or {},
        )
        collected_data = collector.collect_all_data()
        metrics_calculator = MetricsCalculator(collected_data)
        metrics = metrics_calculator.calculate_all()
        metrics["profile"] = collected_data.get("profile") or {}
        metrics["streaks"] = collected_data.get("streaks") or {}
        metrics["goal"] = collected_data.get("goal") or {}
        metrics["word_frequencies"] = collected_data.get("word_frequencies") or {}
        return collected_data, metrics

    def _preview_sections_from_chapters(self, book: JourneyBook, limit: int = 3) -> list[dict[str, Any]]:
        sections: list[dict[str, Any]] = []
        chapters = book.chapters.order_by("chapter_number")[:limit]
        for chapter in chapters:
            sections.append(
                {
                    "chapter_number": chapter.chapter_number,
                    "chapter_title": chapter.chapter_title,
                    "excerpt": self._truncate_excerpt(chapter.content, limit=480),
                    "is_projection": bool(chapter.is_projection),
                }
            )
        return sections

    def _preview_sections_from_fallback(
        self, book: JourneyBook, metrics: dict[str, Any], limit: int = 2
    ) -> list[dict[str, Any]]:
        sections: list[dict[str, Any]] = []
        structure = self._get_structure(book.book_type)
        for idx, chapter in enumerate(structure.get("chapters", [])[:limit], start=1):
            chapter_id = chapter.get("id", f"ch{idx}")
            chapter_text = ChapterFallbacks.get(chapter_id, metrics, book.book_type)
            sections.append(
                {
                    "chapter_number": idx,
                    "chapter_title": chapter.get("title", f"Chapter {idx}"),
                    "excerpt": self._truncate_excerpt(chapter_text, limit=480),
                    "is_projection": bool(chapter.get("is_projection", False)),
                }
            )
        return sections

    def _preview_stats_best_effort(self, book: JourneyBook) -> dict[str, int]:
        try:
            _, metrics = self._collect_preview_metrics(book)
            return self._preview_stats(book, metrics=metrics)
        except (RuntimeError, ValueError, OSError, ObjectDoesNotExist):
            return self._preview_stats(book)

    @staticmethod
    def _preview_stats(book: JourneyBook, metrics: dict[str, Any] | None = None) -> dict[str, int]:
        metrics = metrics or {}
        overview = metrics.get("journey_overview") or {}
        streaks = metrics.get("streaks") or {}
        return {
            "days_of_data": int(book.days_of_data or 0),
            "total_entries": int(overview.get("total_entries") or 0),
            "longest_streak": int(streaks.get("longest_streak") or 0),
        }

    @staticmethod
    def _truncate_excerpt(text: str, limit: int = 480) -> str:
        cleaned = " ".join((text or "").split()).strip()
        if not cleaned:
            return "Sample content is not available yet."
        if len(cleaned) <= limit:
            return cleaned
        truncated = cleaned[:limit].rsplit(" ", 1)[0].strip()
        return f"{truncated}..."

    @staticmethod
    def _preview_title(book: JourneyBook) -> str:
        if book.book_type == JourneyBook.BOOK_TYPE_COMPLETE:
            return "Sample Complete Journey Book"
        return "Sample In-Progress Journey Book"

    @staticmethod
    def _preview_subtitle(book: JourneyBook) -> str:
        goal_titles = list(book.goals.all().values_list("title", flat=True))
        if book.goal_id and book.goal and not goal_titles:
            goal_titles = [book.goal.title]
        if len(goal_titles) == 1:
            goal_title = goal_titles[0]
        elif goal_titles:
            goal_title = "all goals" if (book.metadata or {}).get("selection_mode") == "all" else f"{len(goal_titles)} goals"
        else:
            goal_title = "your journey"
        return (
            f"A sample view of how your narrative would look for {goal_title} "
            f"({book.data_start_date} to {book.data_end_date})."
        )

    @staticmethod
    def _retry_context(book: JourneyBook) -> dict[str, Any]:
        goal_ids = list(book.goals.all().values_list("id", flat=True))
        selection_mode = (book.metadata or {}).get("selection_mode") or (
            "single" if len(goal_ids) == 1 else "multiple" if goal_ids else "overall"
        )
        return {
            "goal_id": str(book.goal_id) if book.goal_id else None,
            "goal_ids": [str(goal_id) for goal_id in goal_ids],
            "include_all_goals": selection_mode == "all",
            "selection_mode": selection_mode,
            "book_type": book.book_type,
        }

    @staticmethod
    def _selection_mode(book: JourneyBook) -> str:
        metadata = book.metadata or {}
        selection_mode = metadata.get("selection_mode")
        if selection_mode in {"overall", "single", "multiple", "all"}:
            return selection_mode
        goal_count = book.goals.count()
        if goal_count == 1:
            return "single"
        if goal_count > 1:
            return "multiple"
        return "overall"

    @staticmethod
    def _build_demo_json_payload(book_type: str, trim_size: str | None = None) -> dict[str, Any]:
        return build_demo_book_payload(book_type=book_type, trim_size=trim_size)

    @staticmethod
    def _get_structure(book_type: str) -> dict:
        if book_type == JourneyBook.BOOK_TYPE_COMPLETE:
            return {
                "chapters": [
                    {"id": "ch1", "title": "Who I Was - Day One", "is_projection": False},
                    {"id": "ch2", "title": "The First 30 Days", "is_projection": False},
                    {"id": "ch3", "title": "The Dip", "is_projection": False},
                    {"id": "ch4", "title": "The Turning Point", "is_projection": False},
                    {"id": "ch5", "title": "The Progress", "is_projection": False},
                    {"id": "ch6", "title": "The Moments", "is_projection": False},
                    {"id": "ch7", "title": "Who I Became", "is_projection": False},
                ],
                "motivational_pages": [
                    "the_day_you_didnt_quit",
                    "before_after",
                    "streak_heatmap",
                    "invisible_wins",
                    "what_you_learned",
                    "three_hardest_days",
                    "milestones_map",
                    "letter_to_past_self",
                ],
            }

        return {
            "chapters": [
                {"id": "ch1", "title": "Who I Was - Day One", "is_projection": False},
                {"id": "ch2", "title": "Your Journey So Far", "is_projection": False},
                {"id": "ch3", "title": "The Challenges", "is_projection": False},
                {"id": "ch4", "title": "If You Keep Going", "is_projection": True},
                {"id": "ch5", "title": "The Future You", "is_projection": True},
            ],
            "motivational_pages": [
                "the_day_you_didnt_quit",
                "streak_heatmap",
                "invisible_wins",
                "what_you_learned",
                "letter_to_past_self",
            ],
        }


class JourneyBookDemoPreviewAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        book_type = request.query_params.get("book_type", JourneyBook.BOOK_TYPE_COMPLETE)
        trim_size = request.query_params.get("trim_size")
        if book_type not in {JourneyBook.BOOK_TYPE_COMPLETE, JourneyBook.BOOK_TYPE_IN_PROGRESS}:
            book_type = JourneyBook.BOOK_TYPE_COMPLETE
        payload = build_demo_book_payload(book_type=book_type, trim_size=trim_size)
        return Response(payload, status=status.HTTP_200_OK)


class JourneyBookDemoPreviewPDFAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    renderer_classes = [PDFBinaryRenderer, JSONRenderer]
    ERROR_TYPE_PDF_ENGINE_ERROR = "PDF_ENGINE_ERROR"

    def get(self, request):
        book_type = request.query_params.get("book_type", JourneyBook.BOOK_TYPE_COMPLETE)
        trim_size = request.query_params.get("trim_size")
        if book_type not in {JourneyBook.BOOK_TYPE_COMPLETE, JourneyBook.BOOK_TYPE_IN_PROGRESS}:
            book_type = JourneyBook.BOOK_TYPE_COMPLETE

        try:
            pdf_bytes, payload = build_demo_pdf_bytes(book_type=book_type, trim_size=trim_size)
        except RuntimeError as exc:
            logger.error("Journey Book demo PDF export failed due to missing PDF engine: %s", exc)
            return JsonResponse(
                {
                    "error_type": self.ERROR_TYPE_PDF_ENGINE_ERROR,
                    "message": "ReportLab is not installed in backend runtime.",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        normalized_trim = payload["print_spec"]["trim_size"]
        filename_trim = normalized_trim.replace(".", "_")

        response = HttpResponse(pdf_bytes.getvalue(), content_type="application/pdf")
        response["Content-Disposition"] = (
            f'attachment; filename="journey_book_demo_{book_type}_{filename_trim}.pdf"'
        )
        response["Cache-Control"] = "no-store"
        return response
