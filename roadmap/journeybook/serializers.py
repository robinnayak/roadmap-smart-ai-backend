from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import APIException
from rest_framework import serializers

from journeybook.models import JourneyBook
from journeybook.services.data_collector import DataCollector
from journeybook.services.print_spec import (
    TRIM_SIZE_5_5_X_8_5,
    TRIM_SIZE_6_X_9,
    TRIM_SIZE_7_X_10,
)


class JourneyBookSerializer(serializers.ModelSerializer):
    book_type_display = serializers.CharField(source="get_book_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    download_url = serializers.SerializerMethodField()
    generation_duration_seconds = serializers.FloatField(read_only=True)
    goal_id = serializers.SerializerMethodField()
    goal_title = serializers.SerializerMethodField()
    error_code = serializers.SerializerMethodField()
    error_display = serializers.SerializerMethodField()
    can_preview_sample = serializers.SerializerMethodField()
    can_retry = serializers.SerializerMethodField()
    retry_context = serializers.SerializerMethodField()

    class Meta:
        model = JourneyBook
        fields = [
            "id",
            "book_type",
            "book_type_display",
            "status",
            "status_display",
            "days_of_data",
            "data_start_date",
            "data_end_date",
            "metadata",
            "download_url",
            "error_message",
            "generation_duration_seconds",
            "goal_id",
            "goal_title",
            "error_code",
            "error_display",
            "can_preview_sample",
            "can_retry",
            "retry_context",
            "created_at",
            "updated_at",
        ]

    def get_download_url(self, obj: JourneyBook) -> str | None:
        if obj.status != JourneyBook.STATUS_READY:
            return None
        request = self.context.get("request")
        url = reverse("journeybook:journeybook-download", args=[obj.id])
        return request.build_absolute_uri(url) if request else url

    @staticmethod
    def get_goal_id(obj: JourneyBook) -> str | None:
        return str(obj.goal_id) if obj.goal_id else None

    @staticmethod
    def get_goal_title(obj: JourneyBook) -> str | None:
        if obj.goal_id and obj.goal:
            return obj.goal.title
        return None

    def get_error_code(self, obj: JourneyBook) -> str | None:
        code, _ = self._map_error(obj)
        return code

    def get_error_display(self, obj: JourneyBook) -> str | None:
        _, display = self._map_error(obj)
        return display

    @staticmethod
    def get_can_preview_sample(obj: JourneyBook) -> bool:
        return obj.status == JourneyBook.STATUS_FAILED

    @staticmethod
    def get_can_retry(obj: JourneyBook) -> bool:
        return obj.status == JourneyBook.STATUS_FAILED

    @staticmethod
    def get_retry_context(obj: JourneyBook) -> dict[str, str | None]:
        return {
            "goal_id": str(obj.goal_id) if obj.goal_id else None,
            "book_type": obj.book_type,
        }

    @staticmethod
    def _map_error(obj: JourneyBook) -> tuple[str | None, str | None]:
        if obj.status != JourneyBook.STATUS_FAILED:
            return None, None

        raw_error = (obj.error_message or "").strip().lower()
        if "reportlab is required" in raw_error:
            return (
                "pdf_dependency_missing",
                "PDF export is temporarily unavailable. You can view a sample and try again.",
            )

        return (
            "generation_failed",
            "We could not generate your Journey Book this time. You can view a sample and try again.",
        )


class JourneyBookGenerateSerializer(serializers.Serializer):
    BOOK_TYPE_AUTO = "auto"
    MODE_REAL = "real"
    MODE_DEMO = "demo"

    goal_id = serializers.UUIDField(required=False, allow_null=True)
    mode = serializers.ChoiceField(
        choices=[MODE_REAL, MODE_DEMO],
        required=False,
        default=MODE_REAL,
    )
    book_type = serializers.ChoiceField(
        choices=[
            JourneyBook.BOOK_TYPE_COMPLETE,
            JourneyBook.BOOK_TYPE_IN_PROGRESS,
            BOOK_TYPE_AUTO,
        ]
    )
    trim_size = serializers.ChoiceField(
        choices=[TRIM_SIZE_5_5_X_8_5, TRIM_SIZE_6_X_9, TRIM_SIZE_7_X_10],
        required=False,
        default=TRIM_SIZE_6_X_9,
    )
    privacy_settings = serializers.DictField(required=False, default=dict)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        mode = attrs.get("mode", self.MODE_REAL)
        if mode == self.MODE_DEMO:
            if attrs.get("book_type") == self.BOOK_TYPE_AUTO:
                attrs["book_type"] = JourneyBook.BOOK_TYPE_COMPLETE
            attrs["eligibility"] = None
            return attrs

        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            raise serializers.ValidationError("Authentication required.")

        goal_id = attrs.get("goal_id")
        if goal_id is not None:
            self._validate_goal_ownership(user=user, goal_id=goal_id)

        collector = DataCollector(
            user=user,
            goal_id=goal_id,
            privacy_settings=attrs.get("privacy_settings") or {},
        )
        eligibility = collector.check_eligibility(goal_id=goal_id)
        attrs["eligibility"] = eligibility

        requested_type = attrs["book_type"]
        if requested_type == JourneyBook.BOOK_TYPE_COMPLETE and not eligibility.get(
            "can_generate_complete"
        ):
            raise serializers.ValidationError(
                {
                    "book_type": "Complete journey book is not eligible for this goal/data window.",
                    "eligibility": eligibility,
                }
            )

        if requested_type == JourneyBook.BOOK_TYPE_IN_PROGRESS and not eligibility.get(
            "can_generate_in_progress"
        ):
            raise serializers.ValidationError(
                {
                    "book_type": "In-progress journey book is not eligible for this goal/data window.",
                    "eligibility": eligibility,
                }
            )

        if requested_type == self.BOOK_TYPE_AUTO:
            if eligibility.get("can_generate_complete"):
                attrs["book_type"] = JourneyBook.BOOK_TYPE_COMPLETE
            elif eligibility.get("can_generate_in_progress"):
                attrs["book_type"] = JourneyBook.BOOK_TYPE_IN_PROGRESS
            else:
                raise serializers.ValidationError(
                    {
                        "book_type": "No eligible journey book type available.",
                        "eligibility": eligibility,
                    }
                )

        self._enforce_rate_limit(user=user)
        return attrs

    @staticmethod
    def _validate_goal_ownership(user, goal_id) -> None:
        try:
            from goal.models import Goal
        except Exception:
            raise serializers.ValidationError({"goal_id": "Goal app is not available."})

        exists = Goal.objects.filter(id=goal_id, user=user).exists()
        if not exists:
            raise serializers.ValidationError({"goal_id": "Goal not found for this user."})

    @staticmethod
    def _enforce_rate_limit(user) -> None:
        now = timezone.now()
        limit_window = timedelta(hours=24)

        active_book = (
            JourneyBook.objects.filter(
                user=user,
                status__in=[JourneyBook.STATUS_QUEUED, JourneyBook.STATUS_GENERATING],
            )
            .order_by("-created_at")
            .first()
        )
        if active_book:
            next_allowed_at = active_book.created_at + limit_window
            raise JourneyBookRateLimitException(
                {
                    "error": "Rate limit",
                    "next_allowed_at": next_allowed_at.isoformat(),
                }
            )

        last_ready = (
            JourneyBook.objects.filter(user=user, status=JourneyBook.STATUS_READY)
            .order_by("-created_at")
            .first()
        )
        if last_ready and now < (last_ready.created_at + limit_window):
            next_allowed_at = last_ready.created_at + limit_window
            raise JourneyBookRateLimitException(
                {
                    "error": "Rate limit",
                    "next_allowed_at": next_allowed_at.isoformat(),
                }
            )


class JourneyBookRateLimitException(APIException):
    status_code = 429
    default_detail = "Rate limit"
    default_code = "rate_limit"

    def __init__(self, detail):
        super().__init__(detail=detail)


class JourneyBookMinimumRequirementsSerializer(serializers.Serializer):
    in_progress_min_days = serializers.IntegerField()
    complete_min_days_if_goal_not_done_or_due = serializers.IntegerField()
    uses_journal_entries = serializers.BooleanField()
    uses_goal_timeline = serializers.BooleanField()


class BookEligibilitySerializer(serializers.Serializer):
    can_generate_complete = serializers.BooleanField()
    can_generate_in_progress = serializers.BooleanField()
    can_choose_type = serializers.BooleanField()
    days_of_data = serializers.IntegerField()
    journal_days = serializers.IntegerField(required=False, default=0)
    goal_age_days = serializers.IntegerField(required=False, default=0)
    goal_completed_or_due = serializers.BooleanField(required=False, default=False)
    complete_unlock_reason = serializers.CharField(required=False, default="not_unlocked")
    minimum_requirements = JourneyBookMinimumRequirementsSerializer(required=False)
    reason_blocked = serializers.CharField(allow_null=True, allow_blank=True)
    goal_id = serializers.CharField(allow_null=True, allow_blank=True)
    goal_title = serializers.CharField(allow_null=True, allow_blank=True)
