from django.contrib import admin

from journal.models import AutoPhraseUsage, JournalEntry, WordCloudAggregate


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = (
        "entry_date",
        "user",
        "is_locked_admin",
        "used_version",
        "parsed_via",
        "sentiment_label",
        "total_word_count",
        "updated_at",
    )
    list_filter = ("used_version", "parsed_via", "sentiment_label", "entry_date")
    search_fields = (
        "user__email",
        "reflection_raw",
        "struggle_raw",
        "tomorrow_priority_raw",
        "gratitude_raw",
        "full_day_input",
    )
    readonly_fields = ("created_at", "updated_at", "locked_at", "parsed_at")
    date_hierarchy = "entry_date"

    @admin.display(boolean=True, description="Locked")
    def is_locked_admin(self, obj):
        from django.utils import timezone

        return timezone.now() > obj.locked_at


@admin.register(WordCloudAggregate)
class WordCloudAggregateAdmin(admin.ModelAdmin):
    list_display = ("user", "updated_at")
    search_fields = ("user__email",)
    readonly_fields = ("updated_at",)


@admin.register(AutoPhraseUsage)
class AutoPhraseUsageAdmin(admin.ModelAdmin):
    list_display = ("user", "usage_date", "count", "updated_at")
    list_filter = ("usage_date",)
    search_fields = ("user__email",)
    readonly_fields = ("updated_at",)
