# ==============================================================================
# roadmap/routine/serializers.py
# ==============================================================================

from rest_framework import serializers
from routine.models import (
    DailyTaskList, DailyTaskItem, HabitTracker,
    HabitCompletion, DisciplineStreak,
)


class HabitTrackerSerializer(serializers.ModelSerializer):
    """
    FIX: linked_goal now returns a summary dict instead of a raw UUID,
         so the frontend can display the goal name without a second API call.
    """
    linked_goal_info = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()

    class Meta:
        model = HabitTracker
        fields = [
            'id', 'name', 'description', 'icon',
            'why_important', 'frequency', 'custom_days',
            'estimated_minutes', 'priority', 'category',
            'linked_goal', 'linked_goal_info',          # raw FK + summary
            'is_active', 'current_streak', 'longest_streak',
            'total_completions', 'last_completed_date',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'current_streak', 'longest_streak',
            'total_completions', 'last_completed_date',
            'created_at', 'updated_at', 'category',
        ]

    def get_linked_goal_info(self, obj):
        if obj.linked_goal_id:
            return {
                'id':       str(obj.linked_goal_id),
                'title':    obj.linked_goal.title,
                'category': obj.linked_goal.primary_category,
            }
        return None

    def get_category(self, obj):
        """Return category from linked goal or a static 'Habit' category."""
        if obj.linked_goal_id:
            return obj.linked_goal.primary_category
        return 'Habit'


class DailyTaskItemSerializer(serializers.ModelSerializer):
    related_goal_info = serializers.SerializerMethodField()
    habit_info        = serializers.SerializerMethodField()
    primary_category  = serializers.SerializerMethodField()

    class Meta:
        model = DailyTaskItem
        fields = [
            'id', 'item_type', 'title', 'description', 'icon',
            'priority', 'estimated_minutes', 'actual_minutes',
            'is_completed', 'completed_at', 'suggested_time',
            'is_skipped', 'skip_reason', 'completion_notes',
            'why_important', 'display_order', 'points_earned', 'primary_category',
            'related_goal_info', 'habit_info',
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

    def get_primary_category(self, obj):
        """Return the primary category from related goal or task item source."""
        if obj.related_goal_id:
            return obj.related_goal.primary_category
        elif obj.habit_id:
            return 'Habit'
        return 'Task'


class DailyTaskItemSummarySerializer(serializers.ModelSerializer):
    """Minimal serializer used inside DailyTaskListSerializer by default."""
    primary_category = serializers.SerializerMethodField()

    class Meta:
        model = DailyTaskItem
        fields = [
            'id', 'item_type', 'title', 'icon',
            'priority', 'estimated_minutes',
            'is_completed', 'is_skipped', 'display_order',
            'primary_category',
        ]

    def get_primary_category(self, obj):
        """Return the primary category from related goal or task item source."""
        if obj.related_goal_id:
            return obj.related_goal.primary_category
        elif obj.habit_id:
            return 'Habit'
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
        qs = obj.tasks.all()
        if self._use_detailed():
            return DailyTaskItemSerializer(qs, many=True).data
        return DailyTaskItemSummarySerializer(qs, many=True).data

    def get_high_priority_tasks(self, obj):
        qs = obj.tasks.filter(priority='high', is_completed=False)
        return DailyTaskItemSerializer(qs, many=True).data

    def get_next_task(self, obj):
        """
        FIX: Cannot order CharField 'priority' alphabetically — 'medium' sorts
             above 'high'. Instead, fetch each priority bucket in order.
        """
        for priority in ('high', 'medium', 'low'):
            task = (
                obj.tasks
                .filter(is_completed=False, is_skipped=False, priority=priority)
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