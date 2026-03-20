import importlib.util

from rest_framework.views import APIView
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny

from common.responses import success_response


# Create your views here.
class BaseProjectMessageApiView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return success_response(
            data={
                "message": "Welcome to the Roadmap Smart Planner API! This is the base endpoint for authentication-related operations.",
                "timestamp": timezone.now().isoformat(),
                "version": "1.0.0",
                "readiness": {
                    "reportlab_available": importlib.util.find_spec("reportlab") is not None,
                },
            },
            message="Request successful",
            status=status.HTTP_200_OK,
        )


class HealthCheckAPIView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return success_response(
            data={"status": "ok"},
            message="Health check successful",
            status=status.HTTP_200_OK,
        )
