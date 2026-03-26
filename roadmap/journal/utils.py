import re
from dataclasses import dataclass
from datetime import datetime, time, timezone as dt_timezone
from html import escape
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from ai.providers.router import create_routed_provider
from authentication.models import Profile
from journal.models import AutoPhraseUsage, JournalEntry, WordCloudAggregate


DEFAULT_TIMEZONE = "Asia/Kathmandu"

STOPWORDS = {
    "the", "and", "that", "this", "with", "have", "from", "your", "about", "just", "into", "when", "what",
    "will", "would", "there", "their", "them", "they", "been", "were", "then", "than", "some", "more",
    "very", "really", "also", "only", "over", "under", "after", "before", "because", "while", "where", "which",
    "today", "yesterday", "tomorrow", "could", "should", "might", "must", "cannot", "cant", "wont", "dont",
    "didnt", "doesnt", "im", "ive", "youre", "theyre", "its", "our", "ours", "his", "her", "hers", "its",
    "for", "are", "was", "had", "has", "did", "not", "but", "you", "too", "all", "out", "off", "how",
    "why", "who", "can", "get", "got", "let", "didn", "wasn", "isn", "ain", "own", "few", "any", "each",
    "per", "via", "yet", "still", "here", "such", "both", "again", "once", "same", "made", "make", "like",
}

SENTIMENT_POSITIVE_WORDS = {
    "happy", "grateful", "great", "progress", "calm", "win", "good", "better", "confident", "love", "proud",
    "focused", "energized", "strong", "clear", "improved", "success", "thankful", "hopeful", "motivated",
}
SENTIMENT_NEGATIVE_WORDS = {
    "sad", "angry", "stressed", "overwhelmed", "tired", "anxious", "bad", "worse", "hate", "stuck", "failed",
    "frustrated", "burnout", "fear", "afraid", "confused", "upset", "pain", "worried", "disappointed",
}

JOURNAL_FIELDS = {"reflection", "struggle", "tomorrow_priority", "gratitude"}
JOURNAL_PARSE_ORDER = ("reflection", "struggle", "tomorrow_priority", "gratitude")
JOURNAL_SECTION_KEYWORDS = {
    "struggle": {"stress", "stressed", "difficult", "hard", "problem", "struggle", "anxious", "worried", "tired", "late", "delay", "pressure"},
    "tomorrow_priority": {"tomorrow", "plan", "planned", "next", "priority", "focus", "start", "finish", "complete"},
    "gratitude": {"grateful", "thankful", "appreciate", "gratitude", "blessed"},
}


@dataclass
class SentimentResult:
    label: str
    score: float
    tags: list[str]


@dataclass
class PhraseResult:
    polished: str
    confidence: float


def resolve_user_timezone(request, user) -> str:
    header_tz = request.headers.get("X-User-Timezone")
    if header_tz:
        try:
            ZoneInfo(header_tz)
            return header_tz
        except Exception as exc:
            raise ValidationError({"timezone": f"Invalid X-User-Timezone header: {exc}"})

    profile, _ = Profile.objects.get_or_create(user=user)
    profile_tz = profile.timezone or DEFAULT_TIMEZONE
    try:
        ZoneInfo(profile_tz)
    except Exception:
        profile_tz = DEFAULT_TIMEZONE
        profile.timezone = DEFAULT_TIMEZONE
        profile.save(update_fields=["timezone"])
    return profile_tz


def today_for_timezone(tz_name: str):
    tz_obj = ZoneInfo(tz_name)
    return timezone.now().astimezone(tz_obj).date()


def build_locked_at(entry_date, tz_name: str):
    tz_obj = ZoneInfo(tz_name)
    end_local = datetime.combine(entry_date, time(23, 59, 59, 999999), tzinfo=tz_obj)
    return end_local.astimezone(dt_timezone.utc)


def is_locked(entry: JournalEntry) -> bool:
    return timezone.now() > entry.locked_at


def clean_text_tokens(text: str) -> list[str]:
    if not text:
        return []
    normalized = re.sub(r"[^a-zA-Z0-9\s]", " ", text.lower())
    tokens = [token.strip() for token in normalized.split() if token.strip()]
    return [token for token in tokens if len(token) >= 3 and token not in STOPWORDS]


def parse_full_day_input(full_day_input: str) -> dict[str, str]:
    text = (full_day_input or "").strip()
    if not text:
        return {field: "" for field in JOURNAL_PARSE_ORDER}

    raw_parts = [part.strip(" ,") for part in re.split(r"[.!?\n;]+|,\s*", text) if part.strip(" ,")]
    sections = {field: [] for field in JOURNAL_PARSE_ORDER}
    unassigned: list[str] = []

    for part in raw_parts:
        tokens = set(clean_text_tokens(part))
        matched_field = None
        for field in ("gratitude", "tomorrow_priority", "struggle"):
            if tokens & JOURNAL_SECTION_KEYWORDS[field]:
                matched_field = field
                break
        if matched_field is None:
            unassigned.append(part)
        else:
            sections[matched_field].append(part)

    if unassigned:
        sections["reflection"].append(unassigned.pop(0))

    for part in unassigned:
        for field in JOURNAL_PARSE_ORDER:
            if not sections[field]:
                sections[field].append(part)
                break
        else:
            sections["reflection"].append(part)

    return {
        field: " ".join(parts).strip()
        for field, parts in sections.items()
    }


def build_field_word_counts(entry: JournalEntry) -> dict[str, int]:
    fields = {
        "reflection": entry.reflection_raw,
        "struggle": entry.struggle_raw,
        "tomorrow_priority": entry.tomorrow_priority_raw,
        "gratitude": entry.gratitude_raw,
    }
    return {key: len(clean_text_tokens(value)) for key, value in fields.items()}


def recalc_wordcloud_for_user(user):
    aggregate, _ = WordCloudAggregate.objects.get_or_create(user=user)
    frequencies: dict[str, int] = {}
    for entry in JournalEntry.objects.filter(user=user).only(
        "reflection_raw",
        "struggle_raw",
        "tomorrow_priority_raw",
        "gratitude_raw",
    ):
        merged = " ".join(
            [
                entry.reflection_raw,
                entry.struggle_raw,
                entry.tomorrow_priority_raw,
                entry.gratitude_raw,
            ]
        )
        for token in clean_text_tokens(merged):
            frequencies[token] = frequencies.get(token, 0) + 1

    aggregate.frequencies = frequencies
    aggregate.save(update_fields=["frequencies", "updated_at"])


def heuristic_sentiment_and_tags(entry: JournalEntry) -> SentimentResult:
    text = " ".join(
        [
            entry.reflection_raw,
            entry.struggle_raw,
            entry.tomorrow_priority_raw,
            entry.gratitude_raw,
        ]
    )
    tokens = clean_text_tokens(text)

    pos = sum(1 for token in tokens if token in SENTIMENT_POSITIVE_WORDS)
    neg = sum(1 for token in tokens if token in SENTIMENT_NEGATIVE_WORDS)
    total = max(len(tokens), 1)
    raw_score = (pos - neg) / total
    score = max(-1.0, min(1.0, round(raw_score, 3)))

    if pos > 0 and neg > 0:
        label = JournalEntry.SENTIMENT_MIXED
    elif score > 0.12:
        label = JournalEntry.SENTIMENT_POSITIVE
    elif score < -0.12:
        label = JournalEntry.SENTIMENT_NEGATIVE
    else:
        label = JournalEntry.SENTIMENT_NEUTRAL

    top_words: dict[str, int] = {}
    for token in tokens:
        top_words[token] = top_words.get(token, 0) + 1
    tags = [w for w, _ in sorted(top_words.items(), key=lambda item: item[1], reverse=True)[:6]]

    return SentimentResult(label=label, score=score, tags=tags)


def _llm_enabled() -> bool:
    import os

    provider_name = os.getenv("JOURNAL_AI_PROVIDER", "").strip().lower()
    return provider_name not in {"off", "disabled", "none"}


def _generate_with_llm(prompt: str, system_prompt: str) -> str:
    import os

    provider = create_routed_provider(
        task_name="journal",
        provider_name=os.getenv("JOURNAL_AI_PROVIDER", "").strip().lower() or None,
        temperature=0.2,
    )
    health = provider.health_check()
    if isinstance(health, dict) and health.get("status") != "healthy":
        raise RuntimeError(health.get("error", "LLM provider unavailable"))
    result = provider.generate_response(prompt=prompt, system_prompt=system_prompt)
    return result.content.strip()


def ai_or_heuristic_sentiment(entry: JournalEntry) -> SentimentResult:
    if _llm_enabled():
        try:
            prompt = (
                "Analyze journal text sentiment and tags. Return strict JSON with keys: "
                "label (positive|neutral|negative|mixed), score (-1 to 1 float), tags (array of up to 6 short words).\n\n"
                f"Text:\n{entry.reflection_raw}\n{entry.struggle_raw}\n{entry.tomorrow_priority_raw}\n{entry.gratitude_raw}"
            )
            content = _generate_with_llm(prompt, "You are a concise sentiment analyzer.")
            import json

            data = json.loads(content)
            label = data.get("label", JournalEntry.SENTIMENT_NEUTRAL)
            if label not in {
                JournalEntry.SENTIMENT_POSITIVE,
                JournalEntry.SENTIMENT_NEUTRAL,
                JournalEntry.SENTIMENT_NEGATIVE,
                JournalEntry.SENTIMENT_MIXED,
            }:
                label = JournalEntry.SENTIMENT_NEUTRAL
            score = float(data.get("score", 0.0))
            score = max(-1.0, min(1.0, score))
            tags = [str(t).strip().lower() for t in data.get("tags", []) if str(t).strip()][:6]
            return SentimentResult(label=label, score=score, tags=tags)
        except Exception:
            pass

    return heuristic_sentiment_and_tags(entry)


def fallback_auto_phrase(text: str) -> PhraseResult:
    if not text or not text.strip():
        return PhraseResult(polished="", confidence=0.5)

    cleaned = re.sub(r"\s+", " ", text.strip())
    cleaned = re.sub(r"\b(i)\b", "I", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(cant)\b", "can't", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(wont)\b", "won't", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(dont)\b", "don't", cleaned, flags=re.IGNORECASE)

    if cleaned and cleaned[-1] not in ".!?":
        cleaned = f"{cleaned}."

    return PhraseResult(polished=cleaned[0].upper() + cleaned[1:] if len(cleaned) > 1 else cleaned.upper(), confidence=0.6)


def ai_or_fallback_autophrase(field: str, text: str) -> PhraseResult:
    if _llm_enabled():
        try:
            prompt = (
                f"Rewrite the following {field} journal text to be clear, concise, and natural. "
                "Keep the original meaning and tone. Return plain text only.\n\n"
                f"Input:\n{text}"
            )
            output = _generate_with_llm(prompt, "You are a helpful journaling writing assistant.")
            if output:
                return PhraseResult(polished=output, confidence=0.85)
        except Exception:
            pass

    return fallback_auto_phrase(text)


def fallback_refine_summary(text: str) -> str:
    if not text or not text.strip():
        return ""

    cleaned = re.sub(r"\s+", " ", text.strip())
    cleaned = re.sub(r"\bi\b", "I", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\biam\b", "I am", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\biaccomplish\b", "I accomplished", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bi learn\b", "I learned", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bi will\b", "I will", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bim\b", "I'm", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bcant\b", "can't", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bdont\b", "don't", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bwont\b", "won't", cleaned, flags=re.IGNORECASE)

    sentence_parts = [part.strip(" ,") for part in re.split(r"[,\n]+", cleaned) if part.strip(" ,")]
    if not sentence_parts:
        return ""

    normalized: list[str] = []
    for part in sentence_parts:
        piece = part[0].upper() + part[1:] if len(part) > 1 else part.upper()
        if piece[-1] not in ".!?":
            piece = f"{piece}."
        normalized.append(piece)
    return " ".join(normalized)


def ai_or_fallback_summary_refine(text: str) -> str:
    if _llm_enabled():
        try:
            prompt = (
                "Refine the grammar, spelling, and punctuation of this daily summary while preserving meaning and tone. "
                "Do not remove details and do not add new information. Return plain text only.\n\n"
                f"Input:\n{text}"
            )
            output = _generate_with_llm(prompt, "You are a concise writing editor.")
            if output:
                return output
        except Exception:
            pass

    return fallback_refine_summary(text)


def consume_autophrase_quota(user, user_timezone: str, feature: str) -> tuple[bool, int, int]:
    local_today = today_for_timezone(user_timezone)
    profile, _ = Profile.objects.get_or_create(user=user)
    limit = 200 if profile.subscription_tier in {"pro_monthly", "lifetime"} else 20

    with transaction.atomic():
        usage, _ = AutoPhraseUsage.objects.select_for_update().get_or_create(
            user=user,
            usage_date=local_today,
            feature=feature,
            defaults={"count": 0},
        )
        if usage.count >= limit:
            return False, limit, 0
        usage.count += 1
        usage.save(update_fields=["count", "updated_at"])

    return True, limit, max(limit - usage.count, 0)


def make_snippet(raw_text: str, query: str, max_len: int = 150) -> str:
    text = re.sub(r"\s+", " ", (raw_text or "").strip())
    if not text:
        return ""

    if not query:
        return escape(text[:max_len])

    pattern = re.compile(re.escape(query), re.IGNORECASE)
    match = pattern.search(text)
    if not match:
        return escape(text[:max_len])

    center_start = max(0, match.start() - 60)
    center_end = min(len(text), match.end() + 60)
    snippet = text[center_start:center_end][:max_len]

    parts: list[str] = []
    cursor = 0
    for snippet_match in pattern.finditer(snippet):
        start, end = snippet_match.span()
        parts.append(escape(snippet[cursor:start]))
        parts.append(f"<mark>{escape(snippet[start:end])}</mark>")
        cursor = end
    parts.append(escape(snippet[cursor:]))

    prefix = "..." if center_start > 0 else ""
    suffix = "..." if center_end < len(text) else ""
    return f"{prefix}{''.join(parts)}{suffix}"


def resolve_search_text(entry: JournalEntry, field: str) -> str:
    if field == "reflection":
        return entry.reflection_raw or ""
    if field == "struggle":
        return entry.struggle_raw or ""
    if field == "tomorrow_priority":
        return entry.tomorrow_priority_raw or ""
    if field == "gratitude":
        return entry.gratitude_raw or ""

    return " ".join(
        [
            entry.reflection_raw or "",
            entry.struggle_raw or "",
            entry.tomorrow_priority_raw or "",
            entry.gratitude_raw or "",
        ]
    )


def apply_search_filters(queryset, *, q: str, field: str, sentiment: str, from_date, to_date):
    if from_date:
        queryset = queryset.filter(entry_date__gte=from_date)
    if to_date:
        queryset = queryset.filter(entry_date__lte=to_date)
    if sentiment and sentiment != "all":
        queryset = queryset.filter(sentiment_label=sentiment)

    if q:
        if field == "reflection":
            queryset = queryset.filter(Q(reflection_raw__icontains=q) | Q(reflection_polished__icontains=q))
        elif field == "struggle":
            queryset = queryset.filter(Q(struggle_raw__icontains=q) | Q(struggle_polished__icontains=q))
        elif field == "tomorrow_priority":
            queryset = queryset.filter(
                Q(tomorrow_priority_raw__icontains=q) | Q(tomorrow_priority_polished__icontains=q)
            )
        elif field == "gratitude":
            queryset = queryset.filter(Q(gratitude_raw__icontains=q) | Q(gratitude_polished__icontains=q))
        else:
            queryset = queryset.filter(
                Q(reflection_raw__icontains=q)
                | Q(struggle_raw__icontains=q)
                | Q(tomorrow_priority_raw__icontains=q)
                | Q(gratitude_raw__icontains=q)
                | Q(reflection_polished__icontains=q)
                | Q(struggle_polished__icontains=q)
                | Q(tomorrow_priority_polished__icontains=q)
                | Q(gratitude_polished__icontains=q)
            )
    return queryset


def compute_streaks(entry_dates: list) -> dict[str, int]:
    if not entry_dates:
        return {"current_streak": 0, "longest_streak": 0}

    sorted_dates = sorted(set(entry_dates))
    longest = 1
    current_run = 1
    for idx in range(1, len(sorted_dates)):
        if (sorted_dates[idx] - sorted_dates[idx - 1]).days == 1:
            current_run += 1
            longest = max(longest, current_run)
        else:
            current_run = 1

    today = timezone.localdate()
    yesterday = today - timezone.timedelta(days=1)
    latest = sorted_dates[-1]
    if latest not in {today, yesterday}:
        current = 0
    else:
        current = 1
        pointer = latest
        existing = set(sorted_dates)
        while (pointer - timezone.timedelta(days=1)) in existing:
            pointer -= timezone.timedelta(days=1)
            current += 1

    return {"current_streak": current, "longest_streak": longest}


def enrich_entry(entry: JournalEntry):
    field_counts = build_field_word_counts(entry)
    entry.field_word_counts = field_counts
    entry.total_word_count = sum(field_counts.values())

    sentiment = ai_or_heuristic_sentiment(entry)
    entry.sentiment_label = sentiment.label
    entry.sentiment_score = sentiment.score
    entry.tags = sentiment.tags
