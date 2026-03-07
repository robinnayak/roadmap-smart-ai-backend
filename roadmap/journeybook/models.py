import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class JourneyBook(models.Model):
    BOOK_TYPE_COMPLETE = "complete"
    BOOK_TYPE_IN_PROGRESS = "in_progress"
    BOOK_TYPE_CHOICES = [
        (BOOK_TYPE_COMPLETE, "Complete"),
        (BOOK_TYPE_IN_PROGRESS, "In Progress"),
    ]

    STATUS_QUEUED = "queued"
    STATUS_GENERATING = "generating"
    STATUS_READY = "ready"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_QUEUED, "Queued"),
        (STATUS_GENERATING, "Generating"),
        (STATUS_READY, "Ready"),
        (STATUS_FAILED, "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="journey_books",
    )
    goal = models.ForeignKey(
        "goal.Goal",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="journey_books",
    )
    goals = models.ManyToManyField(
        "goal.Goal",
        blank=True,
        related_name="journey_book_selections",
    )
    book_type = models.CharField(max_length=20, choices=BOOK_TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_QUEUED)

    data_start_date = models.DateField()
    data_end_date = models.DateField()
    days_of_data = models.IntegerField(default=0)

    pdf_file = models.FileField(upload_to="journey_books/pdf/", null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    privacy_settings = models.JSONField(default=dict, blank=True)

    error_message = models.TextField(blank=True)
    generation_started_at = models.DateTimeField(null=True, blank=True)
    generation_completed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["user", "goal"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"JourneyBook({self.user_id}, {self.book_type}, {self.status})"

    def mark_generating(self):
        self.status = self.STATUS_GENERATING
        self.generation_started_at = timezone.now()
        self.save(update_fields=["status", "generation_started_at", "updated_at"])

    def mark_ready(self, metadata: dict):
        self.status = self.STATUS_READY
        merged_metadata = dict(self.metadata or {})
        merged_metadata.update(metadata or {})
        self.metadata = merged_metadata
        self.generation_completed_at = timezone.now()
        self.save(
            update_fields=["status", "metadata", "generation_completed_at", "updated_at"]
        )

    def mark_failed(self, error: str):
        self.status = self.STATUS_FAILED
        self.error_message = error or ""
        self.generation_completed_at = timezone.now()
        self.save(
            update_fields=[
                "status",
                "error_message",
                "generation_completed_at",
                "updated_at",
            ]
        )

    @property
    def generation_duration_seconds(self):
        if self.generation_started_at and self.generation_completed_at:
            delta = self.generation_completed_at - self.generation_started_at
            return delta.total_seconds()
        return None


class BookChapter(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    journey_book = models.ForeignKey(
        JourneyBook,
        on_delete=models.CASCADE,
        related_name="chapters",
    )
    chapter_number = models.IntegerField()
    chapter_title = models.CharField(max_length=200)
    content = models.TextField()
    word_count = models.IntegerField(default=0)
    is_projection = models.BooleanField(default=False)
    ai_model_used = models.CharField(max_length=100, blank=True)
    generation_time_seconds = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["journey_book", "chapter_number"],
                name="journeybook_unique_book_chapter_number",
            )
        ]

    def __str__(self):
        return f"BookChapter({self.journey_book_id}, {self.chapter_number})"


class BookAsset(models.Model):
    ASSET_TYPE_COMPLETION_CHART = "completion_chart"
    ASSET_TYPE_SENTIMENT_CHART = "sentiment_chart"
    ASSET_TYPE_STREAK_CHART = "streak_chart"
    ASSET_TYPE_HEATMAP = "heatmap"
    ASSET_TYPE_WORDCLOUD = "wordcloud"
    ASSET_TYPE_MILESTONE_TIMELINE = "milestone_timeline"
    ASSET_TYPE_PLACEHOLDER_THEMATIC = "placeholder_thematic"

    ASSET_TYPE_CHOICES = [
        (ASSET_TYPE_COMPLETION_CHART, "Completion Chart"),
        (ASSET_TYPE_SENTIMENT_CHART, "Sentiment Chart"),
        (ASSET_TYPE_STREAK_CHART, "Streak Chart"),
        (ASSET_TYPE_HEATMAP, "Heatmap"),
        (ASSET_TYPE_WORDCLOUD, "Wordcloud"),
        (ASSET_TYPE_MILESTONE_TIMELINE, "Milestone Timeline"),
        (ASSET_TYPE_PLACEHOLDER_THEMATIC, "Placeholder Thematic"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    journey_book = models.ForeignKey(
        JourneyBook,
        on_delete=models.CASCADE,
        related_name="assets",
    )
    asset_type = models.CharField(max_length=40, choices=ASSET_TYPE_CHOICES)
    file_path = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"BookAsset({self.journey_book_id}, {self.asset_type})"


class DerivedMilestone(models.Model):
    CATEGORY_DISCIPLINE = "discipline"
    CATEGORY_CAREER = "career"
    CATEGORY_HEALTH = "health"
    CATEGORY_PERSONAL = "personal"
    CATEGORY_WRITING = "writing"

    CATEGORY_CHOICES = [
        (CATEGORY_DISCIPLINE, "Discipline"),
        (CATEGORY_CAREER, "Career"),
        (CATEGORY_HEALTH, "Health"),
        (CATEGORY_PERSONAL, "Personal"),
        (CATEGORY_WRITING, "Writing"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="derived_milestones",
    )
    label = models.CharField(max_length=200)
    trigger_type = models.CharField(max_length=100)
    achieved_date = models.DateField()
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "trigger_type"],
                name="journeybook_unique_user_trigger_type",
            )
        ]

    def __str__(self):
        return f"DerivedMilestone({self.user_id}, {self.trigger_type})"
