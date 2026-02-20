from django.urls import path
from .views import UserCurrentSituationGoalAPIView, GoalAPIView, CreateGoalWithHierarchyAPIView, GoalListAPIView, GoalDetailAPIView, GoalHierarchyAPIView, TaskDetailApiView

app_name = 'goal'


urlpatterns = [
    path('current-situation/', UserCurrentSituationGoalAPIView.as_view(), name='user-current-situation'),
    path('', GoalAPIView.as_view(), name='goals'),
    path('create-with-hierarchy/', CreateGoalWithHierarchyAPIView.as_view(), name='create-goal-with-hierarchy'),
    path('goals/', GoalListAPIView.as_view(), name='goal-list'),
    path('goals/<uuid:goal_id>/', GoalDetailAPIView.as_view(), name='goal-detail'),
    path('goals/<uuid:goal_id>/hierarchy/', GoalHierarchyAPIView.as_view(), name='goal-hierarchy'),
    path('tasks/<uuid:task_id>/', TaskDetailApiView.as_view(), name='task-detail'),
]