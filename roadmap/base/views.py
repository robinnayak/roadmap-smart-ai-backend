import importlib.util

from rest_framework.views import APIView
from rest_framework.response import Response
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny


# Create your views here.
class BaseProjectMessageApiView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response(
            {
                "message": "Welcome to the Roadmap Smart Planner API! This is the base endpoint for authentication-related operations.",
                "timestamp": timezone.now().isoformat(),
                "version": "1.0.0",
                "readiness": {
                    "reportlab_available": importlib.util.find_spec("reportlab") is not None,
                },
            },
            status=status.HTTP_200_OK,
        )
