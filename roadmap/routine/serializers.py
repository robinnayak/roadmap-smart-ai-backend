# ==============================================================================
# SERIALIZERS FOR DAILY ROUTINE
# ==============================================================================

from rest_framework import serializers
from .models import (
    DailyTaskList, DailyTaskItem, HabitTracker,
    HabitCompletion, DisciplineStreak
)

# Get available tasks and habits
from goal.models import Task, Goal
from .models import HabitTracker
            


class HabitTrackerSerializer(serializers.ModelSerializer):
    """Serializer for HabitTracker"""
    
    class Meta:
        model = HabitTracker
        fields = [
            'id', 'name', 'description', 'icon',
            'why_important', 'frequency', 'custom_days',
            'estimated_minutes', 'priority', 'linked_goal',
            'is_active', 'current_streak', 'longest_streak',
            'total_completions', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'current_streak', 'longest_streak', 'total_completions']


class DailyTaskItemSerializer(serializers.ModelSerializer):
    """Serializer for DailyTaskItem"""
    
    related_goal_info = serializers.SerializerMethodField()
    habit_info = serializers.SerializerMethodField()
    
    class Meta:
        model = DailyTaskItem
        fields = [
            'id', 'item_type', 'title', 'description', 'icon',
            'priority', 'estimated_minutes', 'actual_minutes',
            'is_completed', 'completed_at', 'suggested_time',
            'is_skipped', 'skip_reason', 'completion_notes',
            'why_important', 'display_order', 'points_earned',
            'related_goal_info', 'habit_info',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'completed_at', 'points_earned']
    
    def get_related_goal_info(self, obj):
        if obj.related_goal:
            return {
                'id': str(obj.related_goal.id),
                'title': obj.related_goal.title,
                'category': obj.related_goal.primary_category,
                'priority': obj.related_goal.priority
            }
        return None
    
    def get_habit_info(self, obj):
        if obj.habit:
            return {
                'id': str(obj.habit.id),
                'name': obj.habit.name,
                'icon': obj.habit.icon,
                'current_streak': obj.habit.current_streak
            }
        return None


class DailyTaskListSerializer(serializers.ModelSerializer):
    """Serializer for DailyTaskList with nested tasks"""
    
    tasks = DailyTaskItemSerializer(many=True, read_only=True)
    high_priority_tasks = serializers.SerializerMethodField()
    next_task = serializers.SerializerMethodField()
    
    class Meta:
        model = DailyTaskList
        fields = [
            'id', 'date', 'status', 'total_tasks', 'completed_tasks',
            'completion_percentage', 'is_fully_completed', 'completed_on_time',
            'daily_motivation', 'daily_mantra',
            'created_at', 'updated_at', 'completed_at',
            'tasks', 'high_priority_tasks', 'next_task'
        ]
        read_only_fields = ['id', 'status', 'total_tasks', 'completed_tasks', 'completion_percentage']
    
    def get_high_priority_tasks(self, obj):
        high_tasks = obj.tasks.filter(priority='high', is_completed=False)
        return DailyTaskItemSerializer(high_tasks, many=True).data
    
    def get_next_task(self, obj):
        next_task = obj.tasks.filter(is_completed=False).order_by('-priority', 'display_order').first()
        if next_task:
            return DailyTaskItemSerializer(next_task).data
        return None


class DailyTaskListSummarySerializer(serializers.ModelSerializer):
    """Lightweight serializer for task list summary"""
    
    class Meta:
        model = DailyTaskList
        fields = [
            'id', 'date', 'status', 'total_tasks', 'completed_tasks',
            'completion_percentage', 'is_fully_completed', 'daily_mantra'
        ]


class DisciplineStreakSerializer(serializers.ModelSerializer):
    """Serializer for DisciplineStreak"""
    
    class Meta:
        model = DisciplineStreak
        fields = [
            'id', 'current_streak_days', 'current_streak_start',
            'longest_streak_days', 'longest_streak_start', 'longest_streak_end',
            'total_perfect_days', 'total_days_tracked', 'last_updated'
        ]
        read_only_fields = ['id']
