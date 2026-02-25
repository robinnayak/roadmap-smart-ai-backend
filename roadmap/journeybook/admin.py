from django.contrib import admin

from .models import BookAsset, BookChapter, DerivedMilestone, JourneyBook


@admin.register(JourneyBook)
class JourneyBookAdmin(admin.ModelAdmin):
    list_display = ("user", "book_type", "status", "days_of_data", "created_at")
    list_filter = ("book_type", "status")
    search_fields = ("user__email",)
    readonly_fields = ("generation_started_at", "generation_completed_at", "metadata")


@admin.register(BookChapter)
class BookChapterAdmin(admin.ModelAdmin):
    list_display = ("journey_book", "chapter_number", "chapter_title", "is_projection", "created_at")
    list_filter = ("is_projection",)
    search_fields = ("journey_book__id", "chapter_title")


@admin.register(BookAsset)
class BookAssetAdmin(admin.ModelAdmin):
    list_display = ("journey_book", "asset_type", "created_at")
    list_filter = ("asset_type",)
    search_fields = ("journey_book__id", "file_path")


@admin.register(DerivedMilestone)
class DerivedMilestoneAdmin(admin.ModelAdmin):
    list_display = ("user", "label", "trigger_type", "category", "achieved_date", "created_at")
    list_filter = ("category",)
    search_fields = ("user__email", "label", "trigger_type")
