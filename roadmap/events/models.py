import uuid

from django.conf import settings
from django.db import models


class Event(models.Model):
    EVENT_TYPE_ONE_TIME = "one_time"
    EVENT_TYPE_MULTI_DAY = "multi_day"
    EVENT_TYPE_RECURRING = "recurring"

    EVENT_TYPE_CHOICES = [
        (EVENT_TYPE_ONE_TIME, "One Time"),
        (EVENT_TYPE_MULTI_DAY, "Multi Day"),
        (EVENT_TYPE_RECURRING, "Recurring"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="events",
    )
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True, default="")
    event_type = models.CharField(max_length=20, choices=EVENT_TYPE_CHOICES)
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    is_all_day = models.BooleanField(default=False)
    timezone = models.CharField(max_length=64)
    recurrence = models.JSONField(null=True, blank=True)
    routine_constraint = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "events"
        ordering = ["start_at", "created_at"]
        indexes = [
            models.Index(fields=["user", "start_at"]),
            models.Index(fields=["user", "event_type"]),
        ]

    def __str__(self):
        return f"{self.title} ({self.user_id})"
