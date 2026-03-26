import logging
import time

import httpx

from ai.config import (
    get_ai_debug_enabled,
    get_groq_api_key,
    get_groq_base_url,
    get_groq_model,
    get_llm_max_retries,
    get_llm_request_timeout_seconds,
    get_llm_retry_backoff_seconds,
)
from ai.providers.base import AIResponse, BaseAIProvider

logger = logging.getLogger(__name__)


class GroqProvider(BaseAIProvider):
    provider_name = "groq"

    def __init__(self, model=None, temperature=0.7, max_tokens=None, stream=False):
        resolved_model = model or get_groq_model()
        super().__init__(resolved_model, temperature, max_tokens, stream)
        self.api_key = get_groq_api_key()
        self.base_url = get_groq_base_url().rstrip("/")
        self.timeout = get_llm_request_timeout_seconds()
        self.max_retries = get_llm_max_retries()
        self.retry_backoff_seconds = get_llm_retry_backoff_seconds()
        self.ai_debug_enabled = get_ai_debug_enabled()

    def health_check(self):
        if not self.api_key:
            return {
                "status": "unhealthy",
                "service": self.provider_name,
                "model": self.model,
                "error": "GROQ_API_KEY is not configured",
            }
        return {
            "status": "healthy",
            "service": self.provider_name,
            "model": self.model,
            "base_url": self.base_url,
        }

    def generate_response(self, prompt, system_prompt=None, context=None):
        if not self.api_key:
            raise RuntimeError("Groq provider is not configured. Missing GROQ_API_KEY.")

        messages = [
            {"role": message.role, "content": message.content}
            for message in self.build_messages(prompt, system_prompt, context)
        ]
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "stream": False,
        }
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                started = time.perf_counter()
                response = httpx.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage") or {}
                return AIResponse(
                    content=content,
                    model=self.model,
                    token_used=usage.get("total_tokens"),
                    processing_time=round(time.perf_counter() - started, 4),
                    raw_response=data,
                )
            except Exception as exc:
                last_error = exc
                if attempt >= self.max_retries or not self._is_retryable_error(exc):
                    break
                time.sleep(self.retry_backoff_seconds * (2 ** attempt))
        raise RuntimeError(f"Groq generation failed: {last_error}")

    @staticmethod
    def _is_retryable_error(error: Exception) -> bool:
        if isinstance(error, (httpx.TimeoutException, httpx.NetworkError)):
            return True
        if isinstance(error, httpx.HTTPStatusError):
            return error.response.status_code in {408, 409, 425, 429, 500, 502, 503, 504}
        return False
