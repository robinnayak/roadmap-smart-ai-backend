from django.conf import settings


class GIERolloutPolicyService:
    CODE_ROLLOUT_DISABLED = "gie_rollout_disabled"
    CODE_SERVICE_DEGRADED = "gie_service_degraded"

    MESSAGE_ROLLOUT_DISABLED = "GIE rollout is currently disabled."
    MESSAGE_SERVICE_DEGRADED = "GIE service is temporarily degraded."

    @classmethod
    def current_gate(cls) -> tuple[str, str] | None:
        if not getattr(settings, "GIE_ROLLOUT_ENABLED", True):
            return cls.CODE_ROLLOUT_DISABLED, cls.MESSAGE_ROLLOUT_DISABLED
        if getattr(settings, "GIE_DEGRADED_MODE", False):
            return cls.CODE_SERVICE_DEGRADED, cls.MESSAGE_SERVICE_DEGRADED
        return None
