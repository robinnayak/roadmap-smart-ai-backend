# roadmap/ai/providers/ollama_provider.py

import time
import logging
import httpx

from ai.providers.base import BaseAIProvider, AIResponse, AIMessage

Client = None


def _resolve_client_class():
    """Lazy import to avoid initializing Ollama/httpx during Django startup imports."""
    global Client
    if Client is None:
        from ollama import Client as OllamaClient

        Client = OllamaClient
    return Client
from common.env import get_required_env
from ai.config import (
    get_ollama_model,
    get_ollama_request_timeout_seconds,
    get_ollama_max_retries,
    get_ollama_retry_backoff_seconds,
    get_ollama_trust_env,
    get_ai_debug_enabled,
)

logger = logging.getLogger(__name__)


class OllamaProvider(BaseAIProvider):
    def __init__(self, host=None, model=None, temperature=0.7, max_tokens=None, stream=False):
        resolved_host = host or get_required_env("OLLAMA_HOST")
        resolved_model = model or get_ollama_model()
        super().__init__(resolved_model, temperature, max_tokens, stream)
        self.host = resolved_host
        self.request_timeout_seconds = get_ollama_request_timeout_seconds()
        self.max_retries = get_ollama_max_retries()
        self.retry_backoff_seconds = get_ollama_retry_backoff_seconds()
        self.trust_env = get_ollama_trust_env()
        self.ai_debug_enabled = get_ai_debug_enabled()
        self._client_kwargs = {
            "timeout": self.request_timeout_seconds,
            "trust_env": self.trust_env,
        }
        client_cls = _resolve_client_class()
        self.client = client_cls(host=self.host, **self._client_kwargs)
        if self.ai_debug_enabled:
            logger.info(
                "[AI_DEBUG] OllamaProvider initialized host=%s model=%s timeout=%ss max_retries=%s backoff=%ss trust_env=%s stream=%s",
                self.host,
                self.model,
                self.request_timeout_seconds,
                self.max_retries,
                self.retry_backoff_seconds,
                self.trust_env,
                self.stream,
            )
    
    def health_check(self):
        """Check if Ollama service is healthy and reachable."""
        try:
            # Simple ping to check if Ollama is running
            self.client.list()
            return {
                "status": "healthy",
                "service": "ollama",
                "host": self.host,
                "model": self.model,
                "details": "Ollama service is reachable"
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "service": "ollama",
                "host": self.host,
                "error": str(e),
                "details": "Failed to connect to Ollama service"
            }
    
    def generate_response(self, prompt, system_prompt=None, context=None):
        print("Generating response...")
        print("====="*10)
        if self.ai_debug_enabled:
            logger.info(
                "[AI_DEBUG] Ollama request start model=%s host=%s prompt_chars=%s has_system_prompt=%s context_messages=%s",
                self.model,
                self.host,
                len(prompt or ""),
                bool(system_prompt),
                len(context or []),
            )
            self._debug_model_presence()
        # Build messages once; retries should send the same request payload.
        messages = self.build_messages(prompt, system_prompt, context)

        # Convert to Ollama format
        ollama_messages = [
            {"role": msg.role, "content": msg.content}
            for msg in messages
        ]

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.chat(
                    model=self.model,
                    messages=ollama_messages,
                    stream=self.stream,
                )

                if self.stream:
                    # For streaming responses, handle differently
                    return self._handle_streaming_response(response)

                return AIResponse(
                    content=response['message']['content'],
                    model=self.model,
                    raw_response=response
                )
            except Exception as e:
                last_error = e
                error_kind = self._classify_error(e)
                if self.ai_debug_enabled:
                    logger.exception(
                        "[AI_DEBUG] Ollama request attempt failed attempt=%s/%s kind=%s host=%s model=%s error=%s",
                        attempt + 1,
                        self.max_retries + 1,
                        error_kind,
                        self.host,
                        self.model,
                        str(e),
                    )
                if not self._is_retryable_error(e) or attempt >= self.max_retries:
                    break

                # Rebuild client to clear potentially bad keep-alive state/socket.
                client_cls = _resolve_client_class()
                self.client = client_cls(host=self.host, **self._client_kwargs)

                delay = self.retry_backoff_seconds * (2 ** attempt)
                if delay > 0:
                    if self.ai_debug_enabled:
                        logger.info(
                            "[AI_DEBUG] Retrying Ollama request after %.2fs attempt=%s/%s",
                            delay,
                            attempt + 1,
                            self.max_retries + 1,
                        )
                    time.sleep(delay)
        error_kind = self._classify_error(last_error)
        context = (
            f"kind={error_kind}; host={self.host}; model={self.model}; "
            f"timeout={self.request_timeout_seconds}s; retries={self.max_retries}; trust_env={self.trust_env}"
        )
        raise RuntimeError(f"Ollama generation failed: {str(last_error)} [{context}]")

    def _is_retryable_error(self, error):
        if isinstance(error, (httpx.ReadError, httpx.ConnectError, httpx.RemoteProtocolError, TimeoutError)):
            return True
        # Fallback for wrapped platform-specific socket errors (e.g. WinError 10054).
        message = str(error).lower()
        retry_signatures = (
            "winerror 10054",
            "connection was forcibly closed",
            "connection reset by peer",
            "read error",
            "timed out",
        )
        return any(signature in message for signature in retry_signatures)

    def _classify_error(self, error) -> str:
        if error is None:
            return "UNKNOWN"
        if isinstance(error, (httpx.ConnectError, ConnectionError)):
            return "OLLAMA_CONNECTIVITY"
        if isinstance(error, (httpx.ReadError, httpx.RemoteProtocolError)):
            return "OLLAMA_NETWORK_STREAM"
        if isinstance(error, TimeoutError):
            return "OLLAMA_TIMEOUT"

        text = str(error).lower()
        if "failed to connect to ollama" in text:
            return "OLLAMA_CONNECTIVITY"
        if "model" in text and "not found" in text:
            return "MODEL_MISMATCH"
        if "404" in text and "model" in text:
            return "MODEL_MISMATCH"
        if "timed out" in text or "timeout" in text:
            return "OLLAMA_TIMEOUT"
        if "forcibly closed" in text or "connection reset" in text:
            return "OLLAMA_NETWORK_STREAM"
        return "UNKNOWN"

    def _debug_model_presence(self):
        try:
            models = self.list_models()
            if self.model not in models:
                logger.warning(
                    "[AI_DEBUG] Requested model is not available in local Ollama model list model=%s available_count=%s",
                    self.model,
                    len(models),
                )
            else:
                logger.info(
                    "[AI_DEBUG] Requested model exists in local Ollama model list model=%s",
                    self.model,
                )
        except Exception as exc:
            logger.warning(
                "[AI_DEBUG] Unable to list Ollama models before request host=%s error=%s",
                self.host,
                str(exc),
            )
    
    def _handle_streaming_response(self, response_stream):
        # Collect all streamed content
        full_content = ""
        for chunk in response_stream:
            if 'message' in chunk and 'content' in chunk['message']:
                full_content += chunk['message']['content']
        
        return AIResponse(
            content=full_content,
            model=self.model,
            raw_response={"streamed": True, "content": full_content}
        )
        
    def is_model_available(self):
        try:
            models_response = self.client.list()
            # models_response is a dict with 'models' key
            available_models = [model['name'] for model in models_response.get('models', [])]
            return self.model in available_models
        except Exception as e:
            raise RuntimeError(f"Failed to list models from Ollama: {str(e)}")
        
    def list_models(self):
        try:
            models_response = self.client.list()
            return [model['name'] for model in models_response.get('models', [])]
        except Exception as e:
            raise RuntimeError(f"Failed to list models from Ollama: {str(e)}")
