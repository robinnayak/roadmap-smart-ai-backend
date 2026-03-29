
from django.urls import path
from .views import BaseProjectMessageApiView, HealthCheckAPIView, WaitlistAPIView

urlpatterns = [
    path('health', HealthCheckAPIView.as_view(), name='health-check'),
    path("waitlist/", WaitlistAPIView.as_view(), name="waitlist"),
    path('', BaseProjectMessageApiView.as_view(), name='base-message'),
]
