from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from rest_framework import serializers

from .models import Event

WEEKDAY_VALUES = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


def _validate_timezone_name(value: str) -> str:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise serializers.ValidationError("Invalid IANA timezone.") from exc
    return value


class RecurrenceSerializer(serializers.Serializer):
    frequency = serializers.ChoiceField(choices=("daily", "weekly", "monthly"))
    interval = serializers.IntegerField(min_value=1, max_value=30)
    by_weekday = serializers.ListField(
        child=serializers.ChoiceField(choices=WEEKDAY_VALUES),
        required=False,
        allow_empty=False,
    )
    until_date = serializers.DateField(required=False, allow_null=True)
    count = serializers.IntegerField(required=False, allow_null=True, min_value=1)

    def validate(self, attrs):
        frequency = attrs.get("frequency")
        by_weekday = attrs.get("by_weekday")
        until_date = attrs.get("until_date")
        count = attrs.get("count")

        if frequency == "weekly" and not by_weekday:
            raise serializers.ValidationError({"by_weekday": "This field is required for weekly recurrence."})
        if frequency != "weekly" and by_weekday:
            raise serializers.ValidationError({"by_weekday": "Only allowed when frequency is weekly."})
        if until_date and count:
            raise serializers.ValidationError("Only one of until_date or count can be provided.")
        return attrs


class RoutineConstraintSerializer(serializers.Serializer):
    constraint_mode = serializers.ChoiceField(choices=("hard", "soft"), default="hard")
    buffer_before_minutes = serializers.IntegerField(min_value=0, max_value=180, default=0)
    buffer_after_minutes = serializers.IntegerField(min_value=0, max_value=180, default=0)
    routine_policy = serializers.ChoiceField(choices=("block", "shift", "reduce_load"), default="block")


class EventSerializer(serializers.ModelSerializer):
    recurrence = serializers.JSONField(required=False, allow_null=True)
    routine_constraint = RoutineConstraintSerializer(required=False)

    class Meta:
        model = Event
        fields = [
            "id",
            "title",
            "description",
            "event_type",
            "start_at",
            "end_at",
            "is_all_day",
            "timezone",
            "recurrence",
            "routine_constraint",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_timezone(self, value):
        return _validate_timezone_name(value)

    def validate(self, attrs):
        instance = getattr(self, "instance", None)

        start_at = attrs.get("start_at", getattr(instance, "start_at", None))
        end_at = attrs.get("end_at", getattr(instance, "end_at", None))
        event_type = attrs.get("event_type", getattr(instance, "event_type", None))
        timezone_name = attrs.get("timezone", getattr(instance, "timezone", None))
        recurrence = attrs.get("recurrence", getattr(instance, "recurrence", None))

        if start_at is None or end_at is None:
            return attrs

        if start_at.tzinfo is None or end_at.tzinfo is None:
            raise serializers.ValidationError("start_at and end_at must include timezone offset.")
        if end_at <= start_at:
            raise serializers.ValidationError({"end_at": "end_at must be greater than start_at."})

        if timezone_name:
            _validate_timezone_name(timezone_name)
            event_tz = ZoneInfo(timezone_name)
        else:
            event_tz = start_at.tzinfo

        start_local = start_at.astimezone(event_tz)
        end_local = end_at.astimezone(event_tz)
        if end_local <= start_local:
            raise serializers.ValidationError({"end_at": "end_at must be greater than start_at in event timezone."})

        if event_type == Event.EVENT_TYPE_ONE_TIME and start_local.date() != end_local.date():
            raise serializers.ValidationError(
                {"event_type": "one_time events must start and end on the same local date."}
            )

        if event_type == Event.EVENT_TYPE_MULTI_DAY and start_local.date() == end_local.date():
            raise serializers.ValidationError(
                {"event_type": "multi_day events must span more than one local date."}
            )

        if recurrence is not None:
            recurrence_serializer = RecurrenceSerializer(data=recurrence)
            recurrence_serializer.is_valid(raise_exception=True)
            recurrence = recurrence_serializer.validated_data
            attrs["recurrence"] = recurrence

        if event_type == Event.EVENT_TYPE_RECURRING and recurrence is None:
            raise serializers.ValidationError({"recurrence": "This field is required when event_type is recurring."})
        if event_type in (Event.EVENT_TYPE_ONE_TIME, Event.EVENT_TYPE_MULTI_DAY) and recurrence is not None:
            raise serializers.ValidationError({"recurrence": "Must be null for non-recurring events."})

        if recurrence:
            until_date = recurrence.get("until_date")
            if until_date and until_date < start_local.date():
                raise serializers.ValidationError({"recurrence": {"until_date": "until_date must be on/after start date."}})

        return attrs

    def create(self, validated_data):
        recurrence = validated_data.pop("recurrence", None)
        routine_constraint = validated_data.pop("routine_constraint", None) or {
            "constraint_mode": "hard",
            "buffer_before_minutes": 0,
            "buffer_after_minutes": 0,
            "routine_policy": "block",
        }
        recurrence = self._normalize_recurrence_for_storage(recurrence)
        return Event.objects.create(
            recurrence=recurrence,
            routine_constraint=routine_constraint,
            **validated_data,
        )

    def update(self, instance, validated_data):
        recurrence = validated_data.pop("recurrence", serializers.empty)
        routine_constraint = validated_data.pop("routine_constraint", serializers.empty)

        for field, value in validated_data.items():
            setattr(instance, field, value)

        if recurrence is not serializers.empty:
            instance.recurrence = self._normalize_recurrence_for_storage(recurrence)
        if routine_constraint is not serializers.empty:
            instance.routine_constraint = routine_constraint

        instance.save()
        return instance

    @staticmethod
    def _normalize_recurrence_for_storage(recurrence):
        if recurrence is None:
            return None
        payload = dict(recurrence)
        until_date = payload.get("until_date")
        if until_date is not None:
            payload["until_date"] = until_date.isoformat()
        return payload


class EventRangeQuerySerializer(serializers.Serializer):
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    timezone = serializers.CharField(required=False)
    include_soft_conflicts = serializers.BooleanField(required=False, default=True)

    def validate_timezone(self, value):
        return _validate_timezone_name(value)

    def validate(self, attrs):
        if attrs["end_date"] < attrs["start_date"]:
            raise serializers.ValidationError({"end_date": "end_date must be on/after start_date."})
        if attrs["end_date"] - attrs["start_date"] > timedelta(days=366):
            raise serializers.ValidationError({"end_date": "Range cannot exceed 366 days."})
        return attrs
