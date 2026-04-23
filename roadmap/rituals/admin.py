from django.contrib import admin
from .models import DailyRitualLog, UserRitualProfile


@admin.register(UserRitualProfile)
class UserRitualProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "ritual_tone",
        "morning_alarm_time",
        "night_alarm_time",
        "ritual_active",
        "created_at",
    )
    list_filter = ("ritual_tone", "ritual_active", "created_at")
    search_fields = ("user__username", "user__email", "user__first_name", "user__last_name")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-created_at",)

    fieldsets = (
        ("User & Status", {"fields": ("user", "ritual_active", "ritual_tone")}),
        ("Schedule", {"fields": ("morning_alarm_time", "night_alarm_time")}),
        ("Additional Info", {"fields": ("date_of_birth",)}),
        ("Timestamps", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )


@admin.register(DailyRitualLog)
class DailyRitualLogAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "date",
        "actual_wake_time",
        "night_session_completed",
        "morning_session_completed",
        "ritual_streak_day",
        "created_at",
    )
    list_filter = (
        "date",
        "night_session_completed",
        "morning_session_completed",
        "night_mood",
        "morning_energy",
        "yesterday_task_reflection",
    )
    search_fields = ("user__username", "user__email", "user__first_name", "user__last_name")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-date", "-created_at")

    fieldsets = (
        ("Basic Info", {"fields": ("user", "date", "ritual_streak_day", "wake_delta_minutes")}),
        (
            "Night Session",
            {"fields": ("night_session_completed", "night_session_time", "yesterday_task_reflection", "tomorrow_intent", "night_mood")},
        ),
        (
            "Morning Session",
            {"fields": ("morning_session_completed", "morning_session_time", "actual_wake_time", "snooze_count", "morning_energy")},
        ),
        (
            "Metadata",
            {"fields": ("shown_variants", "created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )