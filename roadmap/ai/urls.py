from django.urls import path
from .views import AIApiView
from .views import (
    AIProcessTextDataCurrentSituation,
    AIHealthCheckView,
    GoalAttributeExtractorAPIView,
    GenerateMileStonesAPIView,
    AIJobStatusAPIView,
)


urlpatterns = [
    path("", AIApiView.as_view(), name="ai-api"),
    path("health-check/", AIHealthCheckView.as_view(), name="ai-health-check"),
    path(
        "process-text-data-current-situation/",
        AIProcessTextDataCurrentSituation.as_view(),
        name="ai-process-text-data-current-situation",
    ),
    path(
        "goal-attribute-extractor/",
        GoalAttributeExtractorAPIView.as_view(),
        name="goal-attribute-extractor",
    ),
    path("jobs/<uuid:job_id>/", AIJobStatusAPIView.as_view(), name="ai-job-status"),
    path("generate-milestones/<uuid:goal_id>/", GenerateMileStonesAPIView.as_view(), name="generate-milestones"),
]
