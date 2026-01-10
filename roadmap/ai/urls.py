from django.urls import path
from .views import AIApiView
from .views import AIProcessTextDataCurrentSituation, AIHealthCheckView

urlpatterns = [
    path("", AIApiView.as_view(), name="ai-api"),
    path("process-text-data-current-situation/", AIProcessTextDataCurrentSituation.as_view(), name="ai-process-text-data-current-situation"),
    path("health-check/", AIHealthCheckView.as_view(), name="ai-health-check"),
]
