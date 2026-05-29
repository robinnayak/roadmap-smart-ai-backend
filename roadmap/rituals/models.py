from datetime import time

from django.conf import settings
from django.db import models
from django.utils import timezone


class UserRitualProfile(models.Model):
    TONE_BRO = "bro"
    TONE_GENTLE = "gentle"
    TONE_SOFT_GIRL = "soft_girl"
    TONE_COACH = "coach"
    TONE_CHOICES = [
        (TONE_BRO, "Bro"),
        (TONE_GENTLE, "Gentle"),
        (TONE_SOFT_GIRL, "Soft Girl"),
        (TONE_COACH, "Coach"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ritual_profile",
    )
    ritual_tone = models.CharField(
        max_length=20,
        choices=TONE_CHOICES,
        default=TONE_GENTLE,
    )
    morning_alarm_time = models.TimeField(default=time(6, 15))
    night_alarm_time = models.TimeField(default=time(22, 0))
    date_of_birth = models.DateField(null=True, blank=True)
    ritual_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user_id"]

    def __str__(self):
        return f"Ritual profile for {self.user}"


class DailyRitualLog(models.Model):
    TASK_REFLECTION_CHOICES = [
        ("done", "Done"),
        ("partial", "Partial"),
        ("missed", "Missed"),
    ]
    NIGHT_MOOD_CHOICES = [
        ("strong", "Strong"),
        ("okay", "Okay"),
        ("rough", "Rough"),
    ]
    MORNING_ENERGY_CHOICES = [
        ("sleepy", "Sleepy"),
        ("neutral", "Neutral"),
        ("energized", "Energized"),
        ("fired", "Fired Up"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="daily_ritual_logs",
    )
    date = models.DateField(default=timezone.localdate, db_index=True)
    shown_variants = models.JSONField(default=dict, blank=True)

    night_session_completed = models.BooleanField(default=False)
    night_session_time = models.TimeField(null=True, blank=True)
    yesterday_task_reflection = models.CharField(
        max_length=20,
        choices=TASK_REFLECTION_CHOICES,
        null=True,
        blank=True,
    )
    tomorrow_intent = models.TextField(null=True, blank=True)
    night_mood = models.CharField(
        max_length=20,
        choices=NIGHT_MOOD_CHOICES,
        null=True,
        blank=True,
    )

    morning_session_completed = models.BooleanField(default=False)
    morning_session_time = models.TimeField(null=True, blank=True)
    actual_wake_time = models.TimeField(null=True, blank=True)
    snooze_count = models.IntegerField(default=0)
    morning_energy = models.CharField(
        max_length=20,
        choices=MORNING_ENERGY_CHOICES,
        null=True,
        blank=True,
    )

    wake_delta_minutes = models.IntegerField(null=True, blank=True)
    ritual_streak_day = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "date"], name="unique_daily_ritual_log"),
        ]
        indexes = [
            models.Index(fields=["user", "date"]),
        ]

    def __str__(self):
        return f"{self.user} ritual log {self.date.isoformat()}"


class RitualMessageHistory(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ritual_message_history",
    )
    trigger_type = models.CharField(max_length=40)
    template_id = models.CharField(max_length=80)
    message = models.TextField()
    tone = models.CharField(max_length=20, choices=UserRitualProfile.TONE_CHOICES)
    shown_on = models.DateField(default=timezone.localdate, db_index=True)
    shown_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-shown_at"]
        indexes = [
            models.Index(fields=["user", "trigger_type", "shown_at"]),
            models.Index(fields=["user", "template_id"]),
        ]

    def __str__(self):
        return f"{self.user} {self.trigger_type} {self.template_id}"
