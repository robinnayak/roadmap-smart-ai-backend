# ==============================================================================
# roadmap/routine/serializers.py
# ==============================================================================

from decimal import Decimal

from rest_framework import serializers
from routine.models import (
    DailyTaskList, DailyTaskItem, HabitTracker, HealthProfile, HabitRecommendation,
    GoalProgressEntry, DailyBrief, HabitCompletion, DisciplineStreak,
    PointsWallet, PointsTransaction, RewardCatalogItem,
)


class GenerateDailyTaskListRequestSerializer(serializers.Serializer):
    date = serializers.DateField(
        required=False,
        input_formats=["%Y-%m-%d"],
        error_messages={"invalid": "Invalid date format. Use YYYY-MM-DD."},
    )
    force = serializers.BooleanField(required=False, default=False)
    day_mode = serializers.ChoiceField(
        required=False,
        choices=["focused", "flex"],
    )
    day_mode_note = serializers.CharField(required=False, allow_blank=True, default="", max_length=500)


class CompleteTaskItemRequestSerializer(serializers.Serializer):
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    actual_minutes = serializers.IntegerField(required=False, allow_null=True, min_value=0)


class SkipTaskItemRequestSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class ReorderRoutineTasksRequestSerializer(serializers.Serializer):
    task_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=True,
        required=True,
    )


class CreateRoutineTaskRequestSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    icon = serializers.CharField(required=False, allow_blank=True, default="✅", max_length=10)
    priority = serializers.ChoiceField(
        choices=DailyTaskItem.PRIORITY_CHOICES,
        required=False,
        default="medium",
    )
    estimated_minutes = serializers.IntegerField(required=False, min_value=1, default=30)
    time_slot = serializers.ChoiceField(
        choices=DailyTaskItem.TIME_SLOT_CHOICES,
        required=False,
        allow_null=True,
        default=None,
    )
    suggested_time = serializers.TimeField(required=False, allow_null=True, default=None)
    why_important = serializers.CharField(required=False, allow_blank=True, default="")
    base_points = serializers.DecimalField(
        required=False,
        max_digits=10,
        decimal_places=4,
        min_value=Decimal("0.0000"),
        default=Decimal("15.0000"),
    )


class UpdateRoutineTaskRequestSerializer(serializers.Serializer):
    title = serializers.CharField(required=False, max_length=255)
    description = serializers.CharField(required=False, allow_blank=True)
    icon = serializers.CharField(required=False, allow_blank=True, max_length=10)
    priority = serializers.ChoiceField(choices=DailyTaskItem.PRIORITY_CHOICES, required=False)
    estimated_minutes = serializers.IntegerField(required=False, min_value=1)
    time_slot = serializers.ChoiceField(
        choices=DailyTaskItem.TIME_SLOT_CHOICES,
        required=False,
        allow_null=True,
    )
    suggested_time = serializers.TimeField(required=False, allow_null=True)
    why_important = serializers.CharField(required=False, allow_blank=True)
    base_points = serializers.DecimalField(
        required=False,
        max_digits=10,
        decimal_places=4,
        min_value=Decimal("0.0000"),
    )


class RewardRedemptionRequestSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, default="")


class HealthProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = HealthProfile
        fields = [
            'id',
            'bad_habits',
            'conditions',
            'on_medication',
            'condition_duration',
            'job_type',
            'job_type_other',
            'work_hours',
            'sleep_pattern',
            'climate',
            'budget_level',
            'age_range',
            'gender',
            'weight_goal',
            'motivation_style',
            'willpower_level',
            'stress_level',
            'past_failures',
            'fitness_level',
            'diet_type',
            'food_restrictions',
            'existing_habits',
            'primary_goal',
            'goal_timeframe',
            'daily_time_available',
            'commitment_words',
            'commitment_person',
            'commitment_emoji',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class HabitSuggestionRequestSerializer(serializers.Serializer):
    goal_id = serializers.UUIDField(required=False)
    profile_id = serializers.UUIDField(required=False)


class HabitSuggestionSnoozeRequestSerializer(serializers.Serializer):
    until_date = serializers.DateField(required=True)


class HabitRecommendationSerializer(serializers.ModelSerializer):
    habit_tracker_id = serializers.UUIDField(source='habit_tracker.id', read_only=True)
    suggested_for_goal_id = serializers.UUIDField(source='suggested_for_goal.id', read_only=True)
    source_health_profile_id = serializers.UUIDField(source='source_health_profile.id', read_only=True)

    class Meta:
        model = HabitRecommendation
        fields = [
            'id',
            'name',
            'icon',
            'category',
            'estimated_minutes',
            'suggested_time',
            'frequency',
            'reason_headline',
            'reason_body',
            'science_badge',
            'rewards',
            'proof_metric_name',
            'status',
            'reviewed_at',
            'snooze_until',
            'habit_tracker_id',
            'suggested_for_goal_id',
            'source_health_profile_id',
            'ai_model_used',
            'generation_batch',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields


class GoalProgressEntrySerializer(serializers.ModelSerializer):
    progress_percentage = serializers.IntegerField(read_only=True)
    date = serializers.DateField(required=False)

    class Meta:
        model = GoalProgressEntry
        fields = [
            'id',
            'date',
            'metric_name',
            'metric_value',
            'metric_unit',
            'metric_direction',
            'domain',
            'metric_start',
            'metric_target',
            'note',
            'progress_percentage',
            'created_at',
        ]
        read_only_fields = ['id', 'progress_percentage', 'created_at']


class DailyBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = DailyBrief
        fields = [
            'id',
            'date',
            'brief_text',
            'habit_completion_yesterday',
            'missed_habits_yesterday',
            'goal_metrics_snapshot',
            'upcoming_events_today',
            'streak_at_generation',
            'track_status',
            'track_status_set_at',
            'generated_at',
            'updated_at',
        ]
        read_only_fields = fields


class TrackStatusRequestSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=['on_track', 'behind', 'struggling'],
        required=True,
    )


class HabitTrackerSerializer(serializers.ModelSerializer):
    """
    FIX: linked_goal now returns a summary dict instead of a raw UUID,
         so the frontend can display the goal name without a second API call.
    """
    linked_goal_info = serializers.SerializerMethodField()
    current_proof = serializers.SerializerMethodField()
    is_system = serializers.BooleanField(read_only=True)
    is_deletable = serializers.BooleanField(read_only=True)

    class Meta:
        model = HabitTracker
        fields = [
            'id', 'name', 'description', 'icon',
            'category', 'why_important',
            'reason_headline', 'reason_body', 'science_badge', 'rewards',
            'proof_metric_name', 'ai_suggested',
            'frequency', 'custom_days', 'estimated_minutes', 'suggested_time', 'time_slot', 'priority',
            'linked_goal', 'linked_goal_info',
            'current_proof',
            'is_active', 'is_system', 'is_deletable',
            'current_streak', 'longest_streak',
            'total_completions', 'last_completed_date',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'user', 'is_system', 'is_deletable',
            'current_streak', 'longest_streak',
            'total_completions', 'last_completed_date',
            'created_at', 'updated_at', 'current_proof',
        ]

    def get_linked_goal_info(self, obj):
        if obj.linked_goal_id:
            return {
                'id':       str(obj.linked_goal_id),
                'title':    obj.linked_goal.title,
                'category': obj.linked_goal.primary_category,
            }
        return None

    def get_current_proof(self, obj):
        return obj.get_current_proof()


class DailyTaskItemSerializer(serializers.ModelSerializer):
    related_goal_info = serializers.SerializerMethodField()
    habit_info        = serializers.SerializerMethodField()
    event_info        = serializers.SerializerMethodField()
    primary_category  = serializers.SerializerMethodField()
    goal_task_id      = serializers.UUIDField(source='goal_task.id', read_only=True)

    class Meta:
        model = DailyTaskItem
        fields = [
            'id', 'item_type', 'title', 'description', 'icon',
            'priority', 'estimated_minutes', 'actual_minutes',
            'is_completed', 'completed_at', 'time_slot', 'suggested_time',
            'is_skipped', 'skip_reason', 'completion_notes',
            'removed_by_user', 'removed_at',
            'why_important', 'display_order', 'base_points', 'points_earned', 'primary_category',
            'goal_task_id',
            'related_goal_info', 'habit_info', 'event_info',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'completed_at', 'points_earned', 'created_at', 'updated_at', 'primary_category']

    def get_related_goal_info(self, obj):
        if obj.related_goal_id:
            return {
                'id':       str(obj.related_goal_id),
                'title':    obj.related_goal.title,
                'category': obj.related_goal.primary_category,
                'priority': obj.related_goal.priority,
            }
        return None

    def get_habit_info(self, obj):
        if obj.habit_id:
            return {
                'id':             str(obj.habit_id),
                'name':           obj.habit.name,
                'icon':           obj.habit.icon,
                'current_streak': obj.habit.current_streak,
                'category':       'Habit',
            }
        return None

    def get_event_info(self, obj):
        if obj.event_id:
            return {
                'id': str(obj.event_id),
                'title': obj.event.title,
                'event_type': obj.event.event_type,
                'timezone': obj.event.timezone,
            }
        return None

    def get_primary_category(self, obj):
        """Return the primary category from related goal or task item source."""
        if obj.related_goal_id:
            return obj.related_goal.primary_category
        elif obj.habit_id:
            return 'Habit'
        elif obj.event_id:
            return 'Event'
        elif obj.item_type == 'journal':
            return 'Journal'
        return 'Task'


class DailyTaskItemSummarySerializer(serializers.ModelSerializer):
    """Minimal serializer used inside DailyTaskListSerializer by default."""
    primary_category = serializers.SerializerMethodField()

    class Meta:
        model = DailyTaskItem
        fields = [
            'id', 'item_type', 'title', 'description', 'icon',
            'priority', 'base_points', 'estimated_minutes',
            'is_completed', 'is_skipped', 'display_order',
            'removed_by_user',
            'primary_category', 'time_slot',
        ]

    def get_primary_category(self, obj):
        """Return the primary category from related goal or task item source."""
        if obj.related_goal_id:
            return obj.related_goal.primary_category
        elif obj.habit_id:
            return 'Habit'
        elif obj.event_id:
            return 'Event'
        elif obj.item_type == 'journal':
            return 'Journal'
        return 'Task'


class DailyTaskListSerializer(serializers.ModelSerializer):
    """
    FIX: Tasks are returned as lightweight summaries by default.
         Pass ?detailed=true to get full DailyTaskItemSerializer output.
         This prevents large payloads on the main routine page load.

    FIX: get_next_task now orders by a priority_order annotation instead of
         the CharField value, so high > medium > low ordering is correct.
    """
    tasks            = serializers.SerializerMethodField()
    high_priority_tasks = serializers.SerializerMethodField()
    next_task        = serializers.SerializerMethodField()

    class Meta:
        model = DailyTaskList
        fields = [
            'id', 'date', 'status',
            'total_tasks', 'completed_tasks', 'completion_percentage',
            'is_fully_completed', 'completed_on_time',
            'daily_motivation', 'daily_mantra',
            'schedule_constraints',
            'created_at', 'updated_at', 'completed_at',
            'tasks', 'high_priority_tasks', 'next_task',
            
        ]
        read_only_fields = [
            'id', 'status', 'total_tasks', 'completed_tasks',
            'completion_percentage', 'created_at', 'updated_at',
        ]

    def _use_detailed(self) -> bool:
        request = self.context.get('request')
        return request and request.query_params.get('detailed', 'false').lower() == 'true'

    def get_tasks(self, obj):
        qs = obj.tasks.filter(removed_by_user=False).select_related('related_goal', 'habit', 'event')
        if self._use_detailed():
            return DailyTaskItemSerializer(qs, many=True).data
        return DailyTaskItemSummarySerializer(qs, many=True).data

    def get_high_priority_tasks(self, obj):
        qs = obj.tasks.select_related('related_goal', 'habit', 'event').filter(
            removed_by_user=False,
            priority='high',
            is_completed=False,
        )
        return DailyTaskItemSerializer(qs, many=True).data

    def get_next_task(self, obj):
        """
        FIX: Cannot order CharField 'priority' alphabetically — 'medium' sorts
             above 'high'. Instead, fetch each priority bucket in order.
        """
        for priority in ('high', 'medium', 'low'):
            task = (
                obj.tasks
                .select_related('related_goal', 'habit', 'event')
                .filter(
                    removed_by_user=False,
                    is_completed=False,
                    is_skipped=False,
                    priority=priority,
                )
                .order_by('display_order')
                .first()
            )
            if task:
                return DailyTaskItemSerializer(task).data
        return None


class DailyTaskListSummarySerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views (e.g. history, dashboard widget)."""

    class Meta:
        model = DailyTaskList
        fields = [
            'id', 'date', 'status', 'total_tasks', 'completed_tasks',
            'completion_percentage', 'is_fully_completed', 'daily_mantra',
        ]


class DisciplineStreakSerializer(serializers.ModelSerializer):

    class Meta:
        model = DisciplineStreak
        fields = [
            'id',
            'current_streak_days', 'current_streak_start',
            'longest_streak_days', 'longest_streak_start', 'longest_streak_end',
            'total_perfect_days', 'total_days_tracked', 'last_updated',
        ]
        read_only_fields = ['id']


class RewardCatalogItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = RewardCatalogItem
        fields = [
            'id',
            'slug',
            'name',
            'description',
            'cost',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields


class PointsTransactionSerializer(serializers.ModelSerializer):
    reward = RewardCatalogItemSerializer(read_only=True)
    task_item_id = serializers.UUIDField(source='task_item.id', read_only=True)

    class Meta:
        model = PointsTransaction
        fields = [
            'id',
            'transaction_type',
            'amount',
            'source_type',
            'note',
            'balance_after',
            'task_item_id',
            'reward',
            'created_at',
        ]
        read_only_fields = fields


class PointsWalletSerializer(serializers.ModelSerializer):
    class Meta:
        model = PointsWallet
        fields = [
            'current_balance',
            'lifetime_earned',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields
