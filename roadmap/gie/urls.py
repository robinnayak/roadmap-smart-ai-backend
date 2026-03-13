from django.urls import path

from gie.views import (
    GIEGoalAdaptAPIView,
    GIEGoalAutofillAPIView,
    GIEGoalFinalizeAPIView,
    GIEGoalPlanAPIView,
    GIEGoalStartAPIView,
    GIEGoalStateAPIView,
    GIEGoalTurnAPIView,
)

app_name = "gie"

urlpatterns = [
    path("goals/start/", GIEGoalStartAPIView.as_view(), name="goals-start"),
    path("goals/<uuid:session_id>/turn/", GIEGoalTurnAPIView.as_view(), name="goals-turn"),
    path("goals/<uuid:session_id>/state/", GIEGoalStateAPIView.as_view(), name="goals-state"),
    path("goals/<uuid:session_id>/autofill/", GIEGoalAutofillAPIView.as_view(), name="goals-autofill"),
    path("goals/<uuid:session_id>/finalize/", GIEGoalFinalizeAPIView.as_view(), name="goals-finalize"),
    path("goals/<uuid:session_id>/plan/", GIEGoalPlanAPIView.as_view(), name="goals-plan"),
    path("goals/<uuid:session_id>/adapt/", GIEGoalAdaptAPIView.as_view(), name="goals-adapt"),
]
