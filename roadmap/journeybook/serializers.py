from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.urls import reverse
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import APIException

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
    goal_ids = serializers.SerializerMethodField()
    goal_titles = serializers.SerializerMethodField()
    selection_mode = serializers.SerializerMethodField()
    error_code = serializers.SerializerMethodField()
    error_display = serializers.SerializerMethodField()
    can_preview_sample = serializers.SerializerMethodField()
    can_retry = serializers.SerializerMethodField()
    retry_context = serializers.SerializerMethodField()
    generation_source = serializers.SerializerMethodField()
    content_stats = serializers.SerializerMethodField()
    asset_generation = serializers.SerializerMethodField()

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
            "goal_ids",
            "goal_titles",
            "selection_mode",
            "error_code",
            "error_display",
            "can_preview_sample",
            "can_retry",
            "retry_context",
            "generation_source",
            "content_stats",
            "asset_generation",
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

    @staticmethod
    def get_goal_ids(obj: JourneyBook) -> list[str]:
        selected = list(obj.goals.all().values_list("id", flat=True))
        if selected:
            return [str(goal_id) for goal_id in selected]
        if obj.goal_id:
            return [str(obj.goal_id)]
        return []

    @staticmethod
    def get_goal_titles(obj: JourneyBook) -> list[str]:
        selected = list(obj.goals.all().values_list("title", flat=True))
        if selected:
            return selected
        if obj.goal_id and obj.goal:
            return [obj.goal.title]
        return []

    def get_selection_mode(self, obj: JourneyBook) -> str:
        metadata = obj.metadata or {}
        selection_mode = metadata.get("selection_mode")
        if selection_mode in {"overall", "single", "multiple", "all"}:
            return selection_mode
        goal_ids = self.get_goal_ids(obj)
        if not goal_ids:
            return "overall"
        if len(goal_ids) == 1:
            return "single"
        return "multiple"

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

    def get_retry_context(self, obj: JourneyBook) -> dict[str, Any]:
        selection_mode = self.get_selection_mode(obj)
        goal_ids = self.get_goal_ids(obj)
        return {
            "goal_id": str(obj.goal_id) if obj.goal_id else None,
            "goal_ids": goal_ids,
            "include_all_goals": selection_mode == "all",
            "selection_mode": selection_mode,
            "book_type": obj.book_type,
        }

    @staticmethod
    def get_generation_source(obj: JourneyBook) -> dict[str, Any]:
        metadata = obj.metadata or {}
        return metadata.get(
            "generation_source",
            {
                "overall": "unknown",
                "chapters": "unknown",
                "motivational_pages": "unknown",
                "counts": {
                    "chapters_ai": 0,
                    "chapters_fallback": 0,
                    "motivational_ai": 0,
                    "motivational_fallback": 0,
                },
            },
        )

    @staticmethod
    def get_content_stats(obj: JourneyBook) -> dict[str, Any]:
        metadata = obj.metadata or {}
        return metadata.get(
            "content_stats",
            {
                "chapter_count": int(metadata.get("chapter_count") or 0),
                "motivational_page_count": len(metadata.get("motivational_pages") or []),
                "word_count": int(metadata.get("word_count") or 0),
                "page_count": int(metadata.get("page_count") or 0),
            },
        )

    @staticmethod
    def get_asset_generation(obj: JourneyBook) -> dict[str, Any]:
        metadata = obj.metadata or {}
        warnings = metadata.get("asset_generation_warnings") or []
        return {
            "status": "degraded" if warnings else "complete",
            "warnings": warnings,
            "generated_count": int(metadata.get("images_generated") or 0),
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
    goal_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=False,
    )
    include_all_goals = serializers.BooleanField(required=False, default=False)
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
            attrs["selection_mode"] = "overall"
            attrs["selected_goals"] = []
            attrs["normalized_goal_ids"] = []
            attrs["representative_goal"] = None
            return attrs

        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            raise serializers.ValidationError("Authentication required.")

        goal_selection = self.normalize_goal_selection(
            user=user,
            goal_id=attrs.get("goal_id"),
            goal_ids=attrs.get("goal_ids"),
            include_all_goals=attrs.get("include_all_goals", False),
        )
        attrs.update(goal_selection)

        collector = DataCollector(
            user=user,
            selected_goals=goal_selection["selected_goals"],
            selection_mode=goal_selection["selection_mode"],
            privacy_settings=attrs.get("privacy_settings") or {},
        )
        eligibility = collector.check_eligibility()
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

        self._enforce_rate_limit(
            user=user,
            selection_mode=goal_selection["selection_mode"],
            normalized_goal_ids=goal_selection["normalized_goal_ids"],
            selected_goals=goal_selection["selected_goals"],
        )
        return attrs

    @staticmethod
    def normalize_goal_selection(
        *,
        user,
        goal_id=None,
        goal_ids=None,
        include_all_goals: bool = False,
    ) -> dict[str, Any]:
        goal_ids = list(goal_ids or [])
        if goal_id and goal_ids:
            raise serializers.ValidationError(
                {"goal_ids": "Use either goal_id or goal_ids, not both."}
            )
        if include_all_goals and (goal_id or goal_ids):
            raise serializers.ValidationError(
                {"include_all_goals": "Cannot be combined with goal_id or goal_ids."}
            )

        try:
            from goal.models import Goal
        except Exception as exc:
            raise serializers.ValidationError({"goal_id": "Goal app is not available."}) from exc

        if goal_id:
            goal_ids = [goal_id]

        if include_all_goals:
            selected_goals = list(Goal.objects.filter(user=user).order_by("created_at", "id"))
            normalized_goal_ids = [str(goal.id) for goal in selected_goals]
            representative_goal = selected_goals[0] if selected_goals else None
            return {
                "selected_goals": selected_goals,
                "normalized_goal_ids": normalized_goal_ids,
                "representative_goal": representative_goal,
                "selection_mode": "all",
                "include_all_goals": True,
                "goal_id": str(representative_goal.id) if representative_goal else None,
            }

        if not goal_ids:
            return {
                "selected_goals": [],
                "normalized_goal_ids": [],
                "representative_goal": None,
                "selection_mode": "overall",
                "include_all_goals": False,
                "goal_id": None,
            }

        deduped_ids: list[str] = []
        for value in goal_ids:
            rendered = str(value)
            if rendered not in deduped_ids:
                deduped_ids.append(rendered)

        goals_by_id = {
            str(goal.id): goal
            for goal in Goal.objects.filter(user=user, id__in=deduped_ids).order_by("created_at", "id")
        }
        missing = [goal_value for goal_value in deduped_ids if goal_value not in goals_by_id]
        if missing:
            raise serializers.ValidationError({"goal_ids": "One or more goals were not found for this user."})

        selected_goals = [goals_by_id[goal_value] for goal_value in deduped_ids]
        representative_goal = selected_goals[0] if selected_goals else None
        selection_mode = "single" if len(selected_goals) == 1 else "multiple"
        return {
            "selected_goals": selected_goals,
            "normalized_goal_ids": deduped_ids,
            "representative_goal": representative_goal,
            "selection_mode": selection_mode,
            "include_all_goals": False,
            "goal_id": str(representative_goal.id) if representative_goal else None,
        }

    @staticmethod
    def _enforce_rate_limit(
        user, selection_mode: str, normalized_goal_ids: list[str], selected_goals: list[Any]
    ) -> None:
        now = timezone.now()
        limit_window = timedelta(hours=24)
        selection_label = JourneyBookGenerateSerializer._selection_label(
            selection_mode=selection_mode,
            selected_goals=selected_goals,
        )

        active_book = next(
            (
                book
                for book in JourneyBook.objects.filter(
                    user=user,
                    status__in=[JourneyBook.STATUS_QUEUED, JourneyBook.STATUS_GENERATING],
                )
                .prefetch_related("goals")
                .order_by("-created_at")
                if JourneyBookGenerateSerializer._book_matches_selection(
                    book=book,
                    selection_mode=selection_mode,
                    normalized_goal_ids=normalized_goal_ids,
                )
            ),
            None,
        )
        if active_book:
            raise JourneyBookRateLimitException(
                {
                    "error": JourneyBookGenerateSerializer._active_generation_message(selection_mode, selection_label),
                    "detail": JourneyBookGenerateSerializer._active_generation_message(selection_mode, selection_label),
                    "next_allowed_at": None,
                }
            )

        last_ready = next(
            (
                book
                for book in JourneyBook.objects.filter(user=user, status=JourneyBook.STATUS_READY)
                .prefetch_related("goals")
                .order_by("-created_at")
                if JourneyBookGenerateSerializer._book_matches_selection(
                    book=book,
                    selection_mode=selection_mode,
                    normalized_goal_ids=normalized_goal_ids,
                )
            ),
            None,
        )
        if last_ready and now < (last_ready.created_at + limit_window):
            next_allowed_at = last_ready.created_at + limit_window
            raise JourneyBookRateLimitException(
                {
                    "error": JourneyBookGenerateSerializer._daily_limit_message(selection_mode, selection_label),
                    "detail": JourneyBookGenerateSerializer._daily_limit_message(selection_mode, selection_label),
                    "next_allowed_at": next_allowed_at.isoformat(),
                }
            )

    @staticmethod
    def _book_matches_selection(
        *, book: JourneyBook, selection_mode: str, normalized_goal_ids: list[str]
    ) -> bool:
        book_goal_ids = list(book.goals.all().values_list("id", flat=True))
        if not book_goal_ids and book.goal_id:
            book_goal_ids = [book.goal_id]
        normalized_book_goal_ids = [str(goal_id) for goal_id in book_goal_ids]

        book_selection_mode = (book.metadata or {}).get("selection_mode")
        if book_selection_mode not in {"overall", "single", "multiple", "all"}:
            if not normalized_book_goal_ids:
                book_selection_mode = "overall"
            elif len(normalized_book_goal_ids) == 1:
                book_selection_mode = "single"
            else:
                book_selection_mode = "multiple"

        return (
            book_selection_mode == selection_mode
            and normalized_book_goal_ids == normalized_goal_ids
        )

    @staticmethod
    def _daily_limit_message(selection_mode: str, selection_label: str | None = None) -> str:
        if selection_mode == "single" and selection_label:
            return f'You cannot generate "{selection_label}" more than once on the same day.'
        if selection_mode == "single":
            return "You cannot generate the same goal more than once on the same day."
        if selection_mode == "multiple":
            return "You cannot generate the same goal combination more than once on the same day."
        if selection_mode == "all":
            return "You cannot generate an all-goals Journey Book more than once on the same day."
        return "You cannot generate the same overall journey book more than once on the same day."

    @staticmethod
    def _active_generation_message(selection_mode: str, selection_label: str | None = None) -> str:
        if selection_mode == "single" and selection_label:
            return f'A Journey Book for "{selection_label}" is already being generated.'
        if selection_mode == "single":
            return "A Journey Book for this goal is already being generated."
        if selection_mode == "multiple":
            return "A Journey Book for this goal combination is already being generated."
        if selection_mode == "all":
            return "An all-goals Journey Book is already being generated."
        return "An overall journey book is already being generated."

    @staticmethod
    def _selection_label(selection_mode: str, selected_goals: list[Any]) -> str | None:
        if selection_mode != "single" or len(selected_goals) != 1:
            return None
        return getattr(selected_goals[0], "title", None)


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
    goal_ids = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    goal_titles = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    selection_mode = serializers.CharField(required=False, default="overall")
