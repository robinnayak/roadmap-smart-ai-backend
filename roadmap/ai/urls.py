from django.urls import path
from .views import AIApiView
from .views import (
    AIProcessTextDataCurrentSituation,
    AIHealthCheckView,
    GoalAttributeExtractorAPIView,
    GenerateMileStonesAPIView,
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
    path("generate-milestones/", GenerateMileStonesAPIView.as_view(), name="generate-milestones"),
]
