import uuid

from django.db import models


class CommunityDiscussion(models.Model):
    CATEGORY_CHOICES = [
        ("general", "General"),
        ("goals", "Goals"),
        ("routines", "Routines"),
        ("habits", "Habits"),
        ("motivation", "Motivation"),
        ("achievements", "Achievements"),
        ("questions", "Questions"),
    ]

    id = models.CharField(max_length=64, primary_key=True)
    title = models.CharField(max_length=255)
    content = models.TextField(blank=True)
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default="general")
    author_id = models.CharField(max_length=64, default=uuid.uuid4, editable=False)
    author_name = models.CharField(max_length=120)
    author_avatar = models.URLField(blank=True, default="")
    author_role = models.CharField(max_length=30, default="member")
    author_level = models.IntegerField(default=1)
    author_badges = models.IntegerField(default=0)
    author_reputation = models.IntegerField(default=0)
    likes = models.IntegerField(default=0)
    comments = models.IntegerField(default=0)
    views = models.IntegerField(default=0)
    is_pinned = models.BooleanField(default=False)
    is_hot = models.BooleanField(default=False)
    last_activity = models.DateTimeField()
    tags = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "community_discussions"
        ordering = ["-is_pinned", "-is_hot", "-last_activity", "-created_at"]
        indexes = [
            models.Index(fields=["category", "last_activity"]),
            models.Index(fields=["is_pinned", "is_hot"]),
        ]


class CommunityTopic(models.Model):
    TREND_CHOICES = [("up", "Up"), ("down", "Down"), ("same", "Same")]

    id = models.CharField(max_length=64, primary_key=True)
    name = models.CharField(max_length=120)
    category = models.CharField(max_length=30, default="general")
    count = models.IntegerField(default=0)
    trend = models.CharField(max_length=10, choices=TREND_CHOICES, default="same")
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "community_topics"
        ordering = ["-count", "name"]


class CommunityEvent(models.Model):
    TYPE_CHOICES = [
        ("meetup", "Meetup"),
        ("webinar", "Webinar"),
        ("challenge", "Challenge"),
        ("workshop", "Workshop"),
    ]

    id = models.CharField(max_length=64, primary_key=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    event_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default="meetup")
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    attendees = models.IntegerField(default=0)
    host_id = models.CharField(max_length=64, default=uuid.uuid4, editable=False)
    host_name = models.CharField(max_length=120)
    host_avatar = models.URLField(blank=True, default="")
    host_role = models.CharField(max_length=30, default="member")
    host_level = models.IntegerField(default=1)
    host_badges = models.IntegerField(default=0)
    host_reputation = models.IntegerField(default=0)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "community_events"
        ordering = ["start_date"]


class CommunityLeaderboardEntry(models.Model):
    CHANGE_CHOICES = [("up", "Up"), ("down", "Down"), ("same", "Same")]

    id = models.CharField(max_length=64, primary_key=True)
    name = models.CharField(max_length=120)
    avatar = models.URLField(blank=True, default="")
    level = models.IntegerField(default=1)
    points = models.IntegerField(default=0)
    streak = models.IntegerField(default=0)
    rank = models.IntegerField(default=1)
    change = models.CharField(max_length=10, choices=CHANGE_CHOICES, default="same")
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "community_leaderboard_entries"
        ordering = ["rank", "-points"]
