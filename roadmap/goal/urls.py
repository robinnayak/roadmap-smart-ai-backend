from django.urls import path
from .views import UserCurrentSituationGoalAPIView, GoalAPIView, CreateGoalWithHierarchyAPIView

urlpatterns = [
    path('current-situation/', UserCurrentSituationGoalAPIView.as_view(), name='user-current-situation'),
    path('', GoalAPIView.as_view(), name='goals'),
    path('create-with-hierarchy/', CreateGoalWithHierarchyAPIView.as_view(), name='create-goal-with-hierarchy'),
    
]