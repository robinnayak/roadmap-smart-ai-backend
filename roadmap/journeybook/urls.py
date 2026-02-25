from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import JourneyBookViewSet

app_name = "journeybook"

router = DefaultRouter()
router.register(r"", JourneyBookViewSet, basename="journeybook")

urlpatterns = [
    path("", include(router.urls)),
]
