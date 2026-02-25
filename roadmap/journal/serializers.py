from rest_framework import serializers

from journal.models import JournalEntry
from journal.utils import JOURNAL_FIELDS, is_locked


class JournalEntrySerializer(serializers.ModelSerializer):
    is_locked = serializers.SerializerMethodField()

    class Meta:
        model = JournalEntry
        fields = [
            "id",
            "entry_date",
            "reflection_raw",
            "struggle_raw",
            "tomorrow_priority_raw",
            "gratitude_raw",
            "full_day_input",
            "reflection_polished",
            "struggle_polished",
            "tomorrow_priority_polished",
            "gratitude_polished",
            "used_version",
            "parsed_via",
            "parsed_at",
            "sentiment_label",
            "sentiment_score",
            "tags",
            "total_word_count",
            "field_word_counts",
            "locked_at",
            "is_locked",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "locked_at",
            "is_locked",
            "created_at",
            "updated_at",
            "sentiment_label",
            "sentiment_score",
            "tags",
            "total_word_count",
            "field_word_counts",
        ]

    def get_is_locked(self, obj):
        return is_locked(obj)


class JournalSearchResultSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    entry_date = serializers.DateField()
    sentiment_label = serializers.CharField()
    tags = serializers.ListField(child=serializers.CharField(), default=list)
    snippet = serializers.CharField()


class AutoPhraseSerializer(serializers.Serializer):
    field = serializers.CharField()
    text = serializers.CharField(allow_blank=True)

    def validate_field(self, value):
        if value not in JOURNAL_FIELDS:
            raise serializers.ValidationError("Invalid field.")
        return value
