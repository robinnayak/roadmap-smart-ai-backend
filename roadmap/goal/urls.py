from django.urls import path
from .views import UserCurrentSituationGoalAPIView, GoalAPIView, CreateGoalWithHierarchyAPIView, GoalListAPIView, GoalDetailAPIView, GoalHierarchyAPIView, TaskDetailApiView, CommitmentContractAPIView
from routine.views import GoalProgressView

app_name = 'goal'


urlpatterns = [
    path('current-situation/', UserCurrentSituationGoalAPIView.as_view(), name='user-current-situation'),
    path('', GoalAPIView.as_view(), name='goals'),
    path('create-with-hierarchy/', CreateGoalWithHierarchyAPIView.as_view(), name='create-goal-with-hierarchy'),
    path('goals/', GoalListAPIView.as_view(), name='goal-list'),
    path('goals/<uuid:goal_id>/', GoalDetailAPIView.as_view(), name='goal-detail'),
    path('goals/<uuid:goal_id>/hierarchy/', GoalHierarchyAPIView.as_view(), name='goal-hierarchy'),
    path('goals/<uuid:goal_id>/progress/', GoalProgressView.as_view(), name='goal-progress'),
    path('tasks/<uuid:task_id>/', TaskDetailApiView.as_view(), name='task-detail'),
    path('commitment-contract/', CommitmentContractAPIView.as_view(), name='commitment-contract'),
]
