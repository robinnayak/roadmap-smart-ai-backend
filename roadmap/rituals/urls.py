from django.urls import path

from .views import (
    AlarmTimeAPIView,
    GoalTasksAPIView,
    MorningEnergyAPIView,
    MorningMessageAPIView,
    NightCloseAPIView,
    NightIntentAPIView,
    NightOpenAPIView,
    NightReflectionAPIView,
    RitualStatusAPIView,
    SnoozeCountAPIView,
    ToneAPIView,
)


app_name = "rituals"


urlpatterns = [
    path("status/", RitualStatusAPIView.as_view(), name="status"),
    path("morning/message/", MorningMessageAPIView.as_view(), name="morning-message"),
    path("morning/energy/", MorningEnergyAPIView.as_view(), name="morning-energy"),
    path("night/open/", NightOpenAPIView.as_view(), name="night-open"),
    path("night/reflection/", NightReflectionAPIView.as_view(), name="night-reflection"),
    path("night/intent/", NightIntentAPIView.as_view(), name="night-intent"),
    path("night/close/", NightCloseAPIView.as_view(), name="night-close"),
    path("goal-tasks/", GoalTasksAPIView.as_view(), name="goal-tasks"),
    path("tone/", ToneAPIView.as_view(), name="tone"),
    path("alarm-time/", AlarmTimeAPIView.as_view(), name="alarm-time"),
    path("snooze-count/", SnoozeCountAPIView.as_view(), name="snooze-count"),
]
