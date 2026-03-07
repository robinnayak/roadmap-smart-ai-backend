from __future__ import annotations

import logging

from rest_framework_simplejwt.authentication import JWTAuthentication

from routine.wake_service import record_first_interaction_for_request

logger = logging.getLogger(__name__)


class WakeInteractionTrackingMiddleware:
    """
    Track first authenticated API interaction per local day for wake-baseline signals.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self._jwt_auth = JWTAuthentication()

    def __call__(self, request):
        self._track_if_authenticated(request)
        return self.get_response(request)

    def _track_if_authenticated(self, request) -> None:
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header or not auth_header.startswith("Bearer "):
            return

        try:
            auth_result = self._jwt_auth.authenticate(request)
        except Exception:
            return

        if not auth_result:
            return

        user, _token = auth_result
        if not getattr(user, "is_authenticated", False):
            return

        header_timezone = request.headers.get("X-User-Timezone")
        try:
            record_first_interaction_for_request(
                user=user,
                request_path=request.path,
                request_method=request.method,
                header_timezone=header_timezone,
            )
        except Exception:
            logger.exception("Wake interaction tracking failed for user %s", getattr(user, "id", "unknown"))
