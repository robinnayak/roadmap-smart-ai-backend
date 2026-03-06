from django.urls import path

from events.views import EventDetailAPIView, EventListCreateAPIView, EventRangeAPIView

urlpatterns = [
    path("", EventListCreateAPIView.as_view(), name="events-list-create"),
    path("range/", EventRangeAPIView.as_view(), name="events-range"),
    path("<uuid:event_id>/", EventDetailAPIView.as_view(), name="events-detail"),
]
