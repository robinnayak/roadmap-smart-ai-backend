from django.contrib import admin

from .models import (
    AdaptiveRoadmapState,
    DailyBrief,
    DailyTaskItem,
    DailyTaskList,
    DisciplineStreak,
    GoalProgressEntry,
    HabitCompletion,
    HabitRecommendation,
    HabitTracker,
    HealthProfile,
)


admin.site.register(DailyTaskList)
admin.site.register(DailyTaskItem)
admin.site.register(HabitTracker)
admin.site.register(HabitCompletion)
admin.site.register(DisciplineStreak)
admin.site.register(AdaptiveRoadmapState)


@admin.register(HealthProfile)
class HealthProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "job_type", "job_type_other", "budget_level", "updated_at")
    search_fields = ("user__email", "job_type_other")
    list_filter = ("job_type", "budget_level", "on_medication", "updated_at")


@admin.register(HabitRecommendation)
class HabitRecommendationAdmin(admin.ModelAdmin):
    list_display = ("user", "name", "category", "status", "created_at")
    search_fields = ("user__email", "name", "reason_headline")
    list_filter = ("status", "category", "created_at")


@admin.register(GoalProgressEntry)
class GoalProgressEntryAdmin(admin.ModelAdmin):
    list_display = ("user", "goal", "metric_name", "metric_value", "metric_unit", "date", "domain")
    search_fields = ("user__email", "goal__title", "metric_name")
    list_filter = ("domain", "metric_direction", "date")


@admin.register(DailyBrief)
class DailyBriefAdmin(admin.ModelAdmin):
    list_display = ("user", "date", "track_status", "generated_at")
    search_fields = ("user__email", "brief_text")
    list_filter = ("track_status", "date")
