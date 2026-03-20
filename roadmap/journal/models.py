import uuid

from django.db import models


class JournalEntry(models.Model):
    VERSION_RAW = "raw"
    VERSION_POLISHED = "polished"
    VERSION_MIXED = "mixed"

    VERSION_CHOICES = [
        (VERSION_RAW, "Raw"),
        (VERSION_POLISHED, "Polished"),
        (VERSION_MIXED, "Mixed"),
    ]

    SENTIMENT_POSITIVE = "positive"
    SENTIMENT_NEUTRAL = "neutral"
    SENTIMENT_NEGATIVE = "negative"
    SENTIMENT_MIXED = "mixed"

    SENTIMENT_CHOICES = [
        (SENTIMENT_POSITIVE, "Positive"),
        (SENTIMENT_NEUTRAL, "Neutral"),
        (SENTIMENT_NEGATIVE, "Negative"),
        (SENTIMENT_MIXED, "Mixed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        "authentication.CustomUser",
        on_delete=models.CASCADE,
        related_name="journal_entries",
    )
    entry_date = models.DateField()

    reflection_raw = models.TextField(default="", blank=True)
    struggle_raw = models.TextField(default="", blank=True)
    tomorrow_priority_raw = models.TextField(default="", blank=True)
    gratitude_raw = models.TextField(default="", blank=True)
    full_day_input = models.TextField(default="", blank=True)

    PARSED_VIA_NONE = "none"
    PARSED_VIA_OLLAMA_FRONTEND = "ollama_frontend"
    PARSED_VIA_BACKEND_HEURISTIC = "backend_heuristic"
    PARSED_VIA_MANUAL = "manual"
    PARSED_VIA_CHOICES = [
        (PARSED_VIA_NONE, "None"),
        (PARSED_VIA_OLLAMA_FRONTEND, "Ollama Frontend"),
        (PARSED_VIA_BACKEND_HEURISTIC, "Backend Heuristic"),
        (PARSED_VIA_MANUAL, "Manual"),
    ]

    reflection_polished = models.TextField(null=True, blank=True)
    struggle_polished = models.TextField(null=True, blank=True)
    tomorrow_priority_polished = models.TextField(null=True, blank=True)
    gratitude_polished = models.TextField(null=True, blank=True)

    used_version = models.CharField(max_length=20, choices=VERSION_CHOICES, default=VERSION_RAW)
    parsed_via = models.CharField(max_length=30, choices=PARSED_VIA_CHOICES, default=PARSED_VIA_NONE)
    parsed_at = models.DateTimeField(null=True, blank=True)

    sentiment_label = models.CharField(
        max_length=20,
        choices=SENTIMENT_CHOICES,
        default=SENTIMENT_NEUTRAL,
    )
    sentiment_score = models.FloatField(default=0.0)
    tags = models.JSONField(default=list, blank=True)
    total_word_count = models.IntegerField(default=0)
    field_word_counts = models.JSONField(default=dict, blank=True)

    locked_at = models.DateTimeField()

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "journal_entries"
        ordering = ["-entry_date", "-updated_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "entry_date"], name="unique_user_entry_date"),
        ]
        indexes = [
            models.Index(fields=["user", "entry_date"]),
            models.Index(fields=["user", "updated_at"]),
        ]

    def __str__(self):
        return f"{self.user.email} - {self.entry_date}"


class WordCloudAggregate(models.Model):
    user = models.OneToOneField(
        "authentication.CustomUser",
        on_delete=models.CASCADE,
        related_name="journal_wordcloud",
    )
    frequencies = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "journal_wordcloud_aggregates"


class AutoPhraseUsage(models.Model):
    FEATURE_AUTO_PHRASE = "auto_phrase"
    FEATURE_SUMMARY_REFINE = "summary_refine"
    FEATURE_CHOICES = [
        (FEATURE_AUTO_PHRASE, "Auto Phrase"),
        (FEATURE_SUMMARY_REFINE, "Summary Refine"),
    ]

    user = models.ForeignKey(
        "authentication.CustomUser",
        on_delete=models.CASCADE,
        related_name="journal_auto_phrase_usages",
    )
    usage_date = models.DateField()
    feature = models.CharField(max_length=30, choices=FEATURE_CHOICES)
    count = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "journal_auto_phrase_usage"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "usage_date", "feature"],
                name="unique_user_autophrase_usage_feature_date",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "usage_date", "feature"]),
        ]
