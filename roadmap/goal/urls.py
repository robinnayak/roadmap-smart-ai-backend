from django.urls import path
from .views import UserCurrentSituationGoalAPIView, GoalAPIView, CreateGoalWithHierarchyAPIView, GoalDetailWithHierarchyAPIView, GoalDetailLightweightAPIView, GoalListAPIView



urlpatterns = [
    path('current-situation/', UserCurrentSituationGoalAPIView.as_view(), name='user-current-situation'),
    path('', GoalAPIView.as_view(), name='goals'),
    path('create-with-hierarchy/', CreateGoalWithHierarchyAPIView.as_view(), name='create-goal-with-hierarchy'),
    path('<uuid:goal_id>/hierarchy/', 
         GoalDetailWithHierarchyAPIView.as_view(), 
         name='goal-detail-hierarchy'),
    
    # Get goal basic info (lightweight)
    path('<uuid:goal_id>/', 
         GoalDetailLightweightAPIView.as_view(), 
         name='goal-detail'),
    
    # List all goals
    path('goals-list/', 
         GoalListAPIView.as_view(), 
         name='goal-list'),
    
]