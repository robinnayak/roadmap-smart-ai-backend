import importlib.util
import logging

from rest_framework.views import APIView
from django.utils import timezone
from rest_framework import status
from django.conf import settings
from rest_framework.permissions import AllowAny

from common.responses import success_response
from common.responses import error_response
from common.email import send_email_via_resend
from .models import WaitlistEntry
from .serializers import WaitlistEntrySerializer

logger = logging.getLogger(__name__)


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


class WaitlistAPIView(APIView):
    permission_classes = [AllowAny]

    def _send_waitlist_welcome_email(self, *, email: str) -> None:
        frontend_base_url = getattr(settings, "FRONTEND_BASE_URL", "").strip()
        text_content = (
            "Welcome to the DayOneGoal waitlist.\n\n"
            "You are on the list for launch updates, early-access onboarding, and pricing announcements."
        )
        html_content = (
            '<div style="font-family: Arial, sans-serif; color: #0f172a; max-width: 640px;">'
            "<h2>Welcome to the DayOneGoal waitlist</h2>"
            "<p>You are on the list for launch updates, early-access onboarding, and pricing announcements.</p>"
        )
        if frontend_base_url:
            text_content += f"\n\nPreview the public site: {frontend_base_url}"
            html_content += f'<p><a href="{frontend_base_url}">Preview DayOneGoal</a></p>'
        html_content += "</div>"
        send_email_via_resend(
            to_email=email,
            subject="Welcome to the DayOneGoal waitlist",
            text_content=text_content,
            html_content=html_content,
        )

    def get(self, request):
        total_count = WaitlistEntry.objects.count()
        return success_response(
            data={"count": total_count},
            message="Waitlist count fetched successfully",
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = WaitlistEntrySerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                message="Waitlist signup failed",
                errors=serializer.errors,
                code="validation_error",
                status=status.HTTP_400_BAD_REQUEST,
            )

        _, created = WaitlistEntry.objects.get_or_create(
            email=serializer.validated_data["email"],
        )
        total_count = WaitlistEntry.objects.count()
        response_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        response_message = (
            "You have been added to the waitlist"
            if created
            else "This email is already on the waitlist"
        )
        if created:
            try:
                self._send_waitlist_welcome_email(email=serializer.validated_data["email"])
            except Exception:
                logger.exception(
                    "Waitlist welcome email dispatch failed for email %s",
                    serializer.validated_data["email"],
                )
        return success_response(
            data={
                "count": total_count,
                "email": serializer.validated_data["email"],
                "created": created,
            },
            message=response_message,
            status=response_status,
        )
