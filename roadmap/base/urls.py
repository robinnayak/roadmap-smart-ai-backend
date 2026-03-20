
from django.urls import path
from .views import BaseProjectMessageApiView, HealthCheckAPIView

urlpatterns = [
    path('health', HealthCheckAPIView.as_view(), name='health-check'),
    path('', BaseProjectMessageApiView.as_view(), name='base-message'),
]
