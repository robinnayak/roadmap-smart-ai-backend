from django.urls import path

from .views import AssistantMessageAPIView


app_name = "assistant"

urlpatterns = [
    path("message/", AssistantMessageAPIView.as_view(), name="message"),
]
