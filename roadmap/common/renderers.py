from http import HTTPStatus

from rest_framework.renderers import JSONRenderer


class ContractJSONRenderer(JSONRenderer):
    """
    Standardize JSON responses to include success/message envelope while preserving
    legacy top-level payload keys for backward compatibility.
    """

    def render(self, data, accepted_media_type=None, renderer_context=None):
        response = (renderer_context or {}).get("response")
        if response is None or data is None:
            return super().render(data, accepted_media_type, renderer_context)

        status_code = getattr(response, "status_code", 200)
        if status_code == 204:
            return super().render(data, accepted_media_type, renderer_context)

        if isinstance(data, dict) and isinstance(data.get("success"), bool) and "message" in data:
            return super().render(data, accepted_media_type, renderer_context)

        is_success = 200 <= status_code < 400
        payload = (
            self._build_success_payload(data, status_code)
            if is_success
            else self._build_error_payload(data, status_code)
        )
        return super().render(payload, accepted_media_type, renderer_context)

    def _build_success_payload(self, data, status_code):
        if isinstance(data, dict):
            message = (
                data.get("message")
                if isinstance(data.get("message"), str) and data.get("message").strip()
                else self._default_success_message(status_code)
            )
            payload = {
                "success": True,
                "message": message,
                "data": data,
            }
            for key, value in data.items():
                payload.setdefault(key, value)
            return payload

        return {
            "success": True,
            "message": self._default_success_message(status_code),
            "data": data,
        }

    def _build_error_payload(self, data, status_code):
        message = self._default_error_message(status_code)
        code = None
        errors = None

        if isinstance(data, dict):
            message = self._extract_message(data, fallback=message)
            code = data.get("code") if isinstance(data.get("code"), str) else None

            if "errors" in data:
                errors = data.get("errors")
            elif "detail" in data and not isinstance(data.get("detail"), str):
                errors = data.get("detail")
            elif "error" in data and not isinstance(data.get("error"), str):
                errors = data.get("error")
            elif "message" not in data and "error" not in data and "detail" not in data:
                errors = data

            payload = {
                "success": False,
                "message": message,
            }
            if code:
                payload["code"] = code
            if errors is not None and errors != message:
                payload["errors"] = errors

            for key, value in data.items():
                payload.setdefault(key, value)
            return payload

        return {
            "success": False,
            "message": message,
            "errors": data,
        }

    @staticmethod
    def _extract_message(payload, fallback):
        for key in ("message", "error", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return fallback

    @staticmethod
    def _default_success_message(status_code):
        if status_code == 201:
            return "Resource created successfully"
        return "Request successful"

    @staticmethod
    def _default_error_message(status_code):
        try:
            return HTTPStatus(status_code).phrase
        except ValueError:
            return "An error occurred"
