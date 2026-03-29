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
    RoutineTaskReorderAPIView,
    RoutineTaskListCreateAPIView,
    RoutineTaskDetailAPIView,
    RoutineTaskRemoveAPIView,
    RoutineTaskRestoreAPIView,
    TodayTaskListAPIView,
    CompleteTaskItemAPIView,
    SkipTaskItemAPIView,
    PointsWalletAPIView,
    PointsTransactionListAPIView,
    RewardCatalogListAPIView,
    RewardRedeemAPIView,
    WeekOverviewAPIView,
    ProgressOverviewAPIView,
    DisciplineStreakAPIView,
    HabitTrackerAPIView,
    HabitDetailAPIView,
    HealthProfileView,
    HealthProfileDetailView,
    HabitSuggestView,
    HabitSuggestionListView,
    HabitSuggestionAcceptView,
    HabitSuggestionRejectView,
    HabitSuggestionSnoozeView,
    ProgressDashboardView,
    DailyBriefView,
    TrackStatusView,
)

urlpatterns = [
    # Generate AI-powered task list
    path('generate/', GenerateDailyTaskListAPIView.as_view(), name='generate-task-list'),

    # Delete a specific routine list
    path('<uuid:routine_id>/', RoutineDetailAPIView.as_view(), name='routine-detail'),
    path('<uuid:routine_id>/reorder/', RoutineTaskReorderAPIView.as_view(), name='routine-task-reorder'),
    path('<uuid:routine_id>/tasks/', RoutineTaskListCreateAPIView.as_view(), name='routine-task-create'),
    
    # Get today's task list (auto-generates if missing)
    path('today/', TodayTaskListAPIView.as_view(), name='today-task-list'),
    
    # Complete task
    path('tasks/<uuid:task_id>/complete/', CompleteTaskItemAPIView.as_view(), name='complete-task'),
    
    # Skip task
    path('tasks/<uuid:task_id>/skip/', SkipTaskItemAPIView.as_view(), name='skip-task'),
    path('tasks/<uuid:task_id>/', RoutineTaskDetailAPIView.as_view(), name='routine-task-detail'),
    path('tasks/<uuid:task_id>/remove/', RoutineTaskRemoveAPIView.as_view(), name='routine-task-remove'),
    path('tasks/<uuid:task_id>/restore/', RoutineTaskRestoreAPIView.as_view(), name='routine-task-restore'),

    # Points wallet and rewards
    path('wallet/', PointsWalletAPIView.as_view(), name='points-wallet'),
    path('wallet/transactions/', PointsTransactionListAPIView.as_view(), name='points-wallet-transactions'),
    path('rewards/', RewardCatalogListAPIView.as_view(), name='reward-catalog-list'),
    path('rewards/<uuid:reward_id>/redeem/', RewardRedeemAPIView.as_view(), name='reward-redeem'),
    
    # Week overview
    path('week/', WeekOverviewAPIView.as_view(), name='week-overview'),

    # Progress analytics report
    path('progress/', ProgressOverviewAPIView.as_view(), name='progress-overview'),
    path('progress/dashboard/', ProgressDashboardView.as_view(), name='progress-dashboard'),
    
    # Discipline streak
    path('streak/', DisciplineStreakAPIView.as_view(), name='discipline-streak'),
    
    # Habit tracker
    path('habits/', HabitTrackerAPIView.as_view(), name='habit-tracker'),
    
    # Habit detail
    path('habits/<uuid:habit_id>/', HabitDetailAPIView.as_view(), name='habit-detail'),

    # Health profile
    path('health-profile/', HealthProfileView.as_view(), name='health-profile'),
    path('health-profile/<uuid:profile_id>/', HealthProfileDetailView.as_view(), name='health-profile-detail'),

    # Habit suggestions
    path('habits/suggest/', HabitSuggestView.as_view(), name='habit-suggest'),
    path('habits/suggestions/', HabitSuggestionListView.as_view(), name='habit-suggestion-list'),
    path('habits/suggestions/<uuid:suggestion_id>/accept/', HabitSuggestionAcceptView.as_view(), name='habit-suggestion-accept'),
    path('habits/suggestions/<uuid:suggestion_id>/reject/', HabitSuggestionRejectView.as_view(), name='habit-suggestion-reject'),
    path('habits/suggestions/<uuid:suggestion_id>/snooze/', HabitSuggestionSnoozeView.as_view(), name='habit-suggestion-snooze'),

    # Daily brief
    path('brief/today/', DailyBriefView.as_view(), name='daily-brief-today'),
    path('brief/track-status/', TrackStatusView.as_view(), name='daily-brief-track-status'),
]
