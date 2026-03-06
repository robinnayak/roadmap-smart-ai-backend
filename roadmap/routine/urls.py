# ==============================================================================
# URL CONFIGURATION
# ==============================================================================

"""
Add to your routines/urls.py
"""

from django.urls import path
from .views import (
    GenerateDailyTaskListAPIView,
    RoutineDetailAPIView,
    TodayTaskListAPIView,
    CompleteTaskItemAPIView,
    SkipTaskItemAPIView,
    WeekOverviewAPIView,
    ProgressOverviewAPIView,
    DisciplineStreakAPIView,
    HabitTrackerAPIView,
    HabitDetailAPIView,
)

urlpatterns = [
    # Generate AI-powered task list
    path('generate/', GenerateDailyTaskListAPIView.as_view(), name='generate-task-list'),

    # Delete a specific routine list
    path('<uuid:routine_id>/', RoutineDetailAPIView.as_view(), name='routine-detail'),
    
    # Get today's task list (auto-generates if missing)
    path('today/', TodayTaskListAPIView.as_view(), name='today-task-list'),
    
    # Complete task
    path('tasks/<uuid:task_id>/complete/', CompleteTaskItemAPIView.as_view(), name='complete-task'),
    
    # Skip task
    path('tasks/<uuid:task_id>/skip/', SkipTaskItemAPIView.as_view(), name='skip-task'),
    
    # Week overview
    path('week/', WeekOverviewAPIView.as_view(), name='week-overview'),

    # Progress analytics report
    path('progress/', ProgressOverviewAPIView.as_view(), name='progress-overview'),
    
    # Discipline streak
    path('streak/', DisciplineStreakAPIView.as_view(), name='discipline-streak'),
    
    # Habit tracker
    path('habits/', HabitTrackerAPIView.as_view(), name='habit-tracker'),
    
    # Habit detail
    path('habits/<uuid:habit_id>/', HabitDetailAPIView.as_view(), name='habit-detail'),
]
