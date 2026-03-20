from datetime import datetime

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from journal.models import AutoPhraseUsage, JournalEntry, WordCloudAggregate
from journal.serializers import AutoPhraseSerializer, JournalEntrySerializer, RefineSummarySerializer
from journal.utils import (
    apply_search_filters,
    ai_or_fallback_autophrase,
    ai_or_fallback_summary_refine,
    build_locked_at,
    compute_streaks,
    consume_autophrase_quota,
    enrich_entry,
    is_locked,
    make_snippet,
    parse_full_day_input,
    recalc_wordcloud_for_user,
    resolve_search_text,
    resolve_user_timezone,
    today_for_timezone,
)


class JournalPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class JournalDatesPagination(PageNumberPagination):
    page_size = 60
    page_size_query_param = "page_size"
    max_page_size = 180


class JournalEntryByDateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _parse_date(date_value):
        if not date_value:
            return None
        try:
            return datetime.strptime(date_value, "%Y-%m-%d").date()
        except ValueError:
            return None

    def _resolve_date(self, request, user_tz):
        query_date = request.query_params.get("date")
        if not query_date:
            return today_for_timezone(user_tz)
        return self._parse_date(query_date)

    def get(self, request):
        user_tz = resolve_user_timezone(request, request.user)
        entry_date = self._resolve_date(request, user_tz)
        if not entry_date:
            return Response(
                {"error": "Invalid date format", "code": "invalid_date"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        entry = JournalEntry.objects.filter(user=request.user, entry_date=entry_date).first()
        if entry:
            payload = JournalEntrySerializer(entry).data
        else:
            locked_at = build_locked_at(entry_date, user_tz)
            payload = {
                "id": None,
                "entry_date": entry_date,
                "reflection_raw": "",
                "struggle_raw": "",
                "tomorrow_priority_raw": "",
                "gratitude_raw": "",
                "full_day_input": "",
                "reflection_polished": None,
                "struggle_polished": None,
                "tomorrow_priority_polished": None,
                "gratitude_polished": None,
                "used_version": "raw",
                "parsed_via": "none",
                "parsed_at": None,
                "sentiment_label": "neutral",
                "sentiment_score": 0,
                "tags": [],
                "total_word_count": 0,
                "field_word_counts": {},
                "locked_at": locked_at,
                "is_locked": timezone.now() > locked_at,
                "created_at": None,
                "updated_at": None,
            }

        return Response(
            {
                "today_local_date": today_for_timezone(user_tz),
                "timezone": user_tz,
                "entry": payload,
            },
            status=status.HTTP_200_OK,
        )

    def put(self, request):
        user_tz = resolve_user_timezone(request, request.user)
        entry_date = self._resolve_date(request, user_tz)
        if not entry_date:
            return Response(
                {"error": "Invalid date format", "code": "invalid_date"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        existing = JournalEntry.objects.filter(user=request.user, entry_date=entry_date).first()
        if existing and is_locked(existing):
            return Response(
                {"error": "Journal entry is locked.", "code": "entry_locked"},
                status=status.HTTP_403_FORBIDDEN,
            )

        if not existing:
            locked_at = build_locked_at(entry_date, user_tz)
            if timezone.now() > locked_at:
                return Response(
                    {
                        "error": "This entry date is already locked and cannot be created.",
                        "code": "entry_locked",
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

        serializer = JournalEntrySerializer(existing, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            if existing:
                entry = serializer.save()
            else:
                entry = serializer.save(
                    user=request.user,
                    entry_date=entry_date,
                    locked_at=build_locked_at(entry_date, user_tz),
                )

            self._apply_full_day_parsing(entry)

            enrich_entry(entry)
            entry.save(
                update_fields=[
                    "reflection_raw",
                    "struggle_raw",
                    "tomorrow_priority_raw",
                    "gratitude_raw",
                    "full_day_input",
                    "reflection_polished",
                    "struggle_polished",
                    "tomorrow_priority_polished",
                    "gratitude_polished",
                    "used_version",
                    "parsed_via",
                    "parsed_at",
                    "sentiment_label",
                    "sentiment_score",
                    "tags",
                    "total_word_count",
                    "field_word_counts",
                    "updated_at",
                ]
            )

        recalc_wordcloud_for_user(request.user)

        return Response(
            {
                "today_local_date": today_for_timezone(user_tz),
                "timezone": user_tz,
                "entry": JournalEntrySerializer(entry).data,
            },
            status=status.HTTP_200_OK,
        )

    @staticmethod
    def _apply_full_day_parsing(entry: JournalEntry):
        if not (entry.full_day_input or "").strip():
            if entry.parsed_via == JournalEntry.PARSED_VIA_BACKEND_HEURISTIC:
                entry.parsed_via = JournalEntry.PARSED_VIA_NONE
                entry.parsed_at = None
            return

        field_map = {
            "reflection": "reflection_raw",
            "struggle": "struggle_raw",
            "tomorrow_priority": "tomorrow_priority_raw",
            "gratitude": "gratitude_raw",
        }
        blank_fields = [field for field, attr in field_map.items() if not getattr(entry, attr).strip()]
        if not blank_fields:
            return

        parsed_sections = parse_full_day_input(entry.full_day_input)
        populated_any = False
        for field in blank_fields:
            parsed_value = parsed_sections.get(field, "").strip()
            if parsed_value:
                setattr(entry, field_map[field], parsed_value)
                populated_any = True

        if populated_any:
            entry.parsed_via = JournalEntry.PARSED_VIA_BACKEND_HEURISTIC
            entry.parsed_at = timezone.now()


class JournalAutoPhraseAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user_tz = resolve_user_timezone(request, request.user)
        allowed, limit, remaining = consume_autophrase_quota(
            request.user,
            user_tz,
            AutoPhraseUsage.FEATURE_AUTO_PHRASE,
        )
        if not allowed:
            return Response(
                {
                    "error": f"Daily auto-phrase limit exceeded ({limit}/day).",
                    "code": "auto_phrase_rate_limited",
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        serializer = AutoPhraseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = ai_or_fallback_autophrase(
            serializer.validated_data["field"],
            serializer.validated_data["text"],
        )

        return Response(
            {
                "polished": result.polished,
                "confidence": result.confidence,
                "daily_limit": limit,
                "remaining_today": remaining,
            },
            status=status.HTTP_200_OK,
        )


class JournalSummaryRefineAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user_tz = resolve_user_timezone(request, request.user)
        allowed, limit, remaining = consume_autophrase_quota(
            request.user,
            user_tz,
            AutoPhraseUsage.FEATURE_SUMMARY_REFINE,
        )
        if not allowed:
            return Response(
                {
                    "error": f"Daily summary-refine limit exceeded ({limit}/day).",
                    "code": "summary_refine_rate_limited",
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        serializer = RefineSummarySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        refined_text = ai_or_fallback_summary_refine(serializer.validated_data["text"])
        return Response(
            {
                "refined_text": refined_text,
                "daily_limit": limit,
                "remaining_today": remaining,
            },
            status=status.HTTP_200_OK,
        )


class JournalSearchAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        field = (request.query_params.get("field") or "all").strip()
        sentiment = (request.query_params.get("sentiment") or "all").strip()
        from_value = request.query_params.get("from")
        to_value = request.query_params.get("to")

        from_date = JournalEntryByDateAPIView._parse_date(from_value)
        to_date = JournalEntryByDateAPIView._parse_date(to_value)

        if from_value and not from_date:
            return Response({"error": "Invalid from date", "code": "invalid_from_date"}, status=400)
        if to_value and not to_date:
            return Response({"error": "Invalid to date", "code": "invalid_to_date"}, status=400)

        queryset = JournalEntry.objects.filter(user=request.user).order_by("-entry_date", "-updated_at")
        queryset = apply_search_filters(
            queryset,
            q=q,
            field=field,
            sentiment=sentiment,
            from_date=from_date,
            to_date=to_date,
        )

        paginator = JournalPagination()
        page = paginator.paginate_queryset(queryset, request)

        results = []
        for entry in page:
            source_text = resolve_search_text(entry, field)
            snippet = make_snippet(source_text, q, max_len=150)
            results.append(
                {
                    "id": entry.id,
                    "entry_date": entry.entry_date,
                    "sentiment_label": entry.sentiment_label,
                    "tags": entry.tags or [],
                    "snippet": snippet,
                }
            )

        return paginator.get_paginated_response(results)


class JournalDatesAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        dates_qs = JournalEntry.objects.filter(user=request.user).order_by("-entry_date").values_list("entry_date", flat=True)
        paginator = JournalDatesPagination()
        page = paginator.paginate_queryset(list(dates_qs), request)
        payload = [{"entry_date": value} for value in page]
        return paginator.get_paginated_response(payload)


class JournalStatsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        dates = list(JournalEntry.objects.filter(user=request.user).values_list("entry_date", flat=True))
        streaks = compute_streaks(dates)
        return Response(
            {
                "total_entries": len(dates),
                "current_streak": streaks["current_streak"],
                "longest_streak": streaks["longest_streak"],
            },
            status=status.HTTP_200_OK,
        )


class JournalWordCloudAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        limit_value = request.query_params.get("limit", "50")
        try:
            limit = max(1, min(int(limit_value), 200))
        except ValueError:
            limit = 50

        aggregate, _ = WordCloudAggregate.objects.get_or_create(user=request.user)
        frequencies = aggregate.frequencies or {}
        top_items = sorted(frequencies.items(), key=lambda item: item[1], reverse=True)[:limit]

        return Response(
            {
                "words": [{"word": word, "count": count} for word, count in top_items],
            },
            status=status.HTTP_200_OK,
        )
