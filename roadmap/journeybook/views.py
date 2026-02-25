from __future__ import annotations

import os
import time
from datetime import date

from django.core.files.base import ContentFile
from django.http import FileResponse
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from journeybook.models import BookAsset, BookChapter, DerivedMilestone, JourneyBook
from journeybook.serializers import (
    BookEligibilitySerializer,
    JourneyBookGenerateSerializer,
    JourneyBookSerializer,
)
from journeybook.services.ai_generator import AIGenerator
from journeybook.services.data_collector import DataCollector
from journeybook.services.image_generator import ImageGenerator
from journeybook.services.metrics_calculator import MetricsCalculator
from journeybook.services.pdf_builder import PDFBuilder


class JourneyBookViewSet(ModelViewSet):
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

        goal_id = validated.get("goal_id")
        privacy_settings = validated.get("privacy_settings") or {}
        collector = DataCollector(
            user=request.user,
            goal_id=goal_id,
            privacy_settings=privacy_settings,
        )
        collected_data = collector.collect_all_data()
        eligibility = validated.get("eligibility") or collector.check_eligibility(goal_id=goal_id)

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
            goal_id=goal_id,
            book_type=validated["book_type"],
            status=JourneyBook.STATUS_QUEUED,
            data_start_date=start_date,
            data_end_date=end_date,
            days_of_data=int(eligibility.get("days_of_data") or 0),
            privacy_settings=privacy_settings,
        )

        try:
            self._generate_sync(book=book, data=collected_data, metrics=metrics)
        except Exception:
            pass

        output = JourneyBookSerializer(book, context={"request": request})
        return Response(output.data, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        book = self.get_object()
        if book.pdf_file:
            book.pdf_file.delete(save=False)
        book.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["get"])
    def eligibility(self, request):
        goal_id = request.query_params.get("goal_id")
        collector = DataCollector(request.user, goal_id=goal_id)
        eligibility = collector.check_eligibility(goal_id=goal_id)
        serializer = BookEligibilitySerializer(instance=eligibility)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        book = self.get_object()
        if book.status != JourneyBook.STATUS_READY or not book.pdf_file:
            return Response({"error": "Book not ready"}, status=status.HTTP_404_NOT_FOUND)

        response = FileResponse(book.pdf_file.open("rb"), content_type="application/pdf")
        response["Content-Disposition"] = (
            f'attachment; filename="journey_book_{str(book.id)[:8]}.pdf"'
        )
        return response

    def _generate_sync(self, book: JourneyBook, data: dict, metrics: dict) -> None:
        book.mark_generating()
        try:
            ai_gen = AIGenerator()
            img_gen = ImageGenerator(metrics)
            structure = self._get_structure(book.book_type)

            chapters_text: list[str] = []
            ai_model_used = os.getenv("JOURNEYBOOK_MODEL", "gpt-oss:20b-cloud")

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
            except Exception:
                pass

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
        except Exception as exc:
            book.mark_failed(str(exc))
            raise

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
