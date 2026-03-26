import logging
from dataclasses import dataclass

from ai.config import ProviderRoute, get_provider_routes
from ai.providers.base import AIResponse, BaseAIProvider
from ai.providers.groq_provider import GroqProvider
from ai.providers.ollama_provider import OllamaProvider
from ai.providers.openrouter_provider import OpenRouterProvider

logger = logging.getLogger(__name__)


PROVIDER_CLASS_MAP = {
    "ollama": OllamaProvider,
    "groq": GroqProvider,
    "openrouter": OpenRouterProvider,
}


@dataclass
class RoutedCallMetadata:
    provider: str
    model: str


class RoutedAIProvider(BaseAIProvider):
    def __init__(
        self,
        *,
        task_name: str,
        provider_name: str | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        stream: bool = False,
    ):
        self.task_name = task_name
        self.routes = get_provider_routes(task_name=task_name, provider_name=provider_name, model=model)
        super().__init__(self.routes[0].model, temperature, max_tokens, stream)
        self.last_provider_name = self.routes[0].provider_name
        self.last_model_name = self.routes[0].model

    def generate_response(self, prompt: str, system_prompt=None, context=None) -> AIResponse:
        failures: list[str] = []
        for route in self.routes:
            provider = self._build_provider(route)
            try:
                response = provider.generate_response(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    context=context,
                )
                if not (response.content or "").strip():
                    raise RuntimeError("Provider returned empty content")
                self.last_provider_name = route.provider_name
                self.last_model_name = response.model or route.model
                self.model = self.last_model_name
                raw_response = response.raw_response
                if isinstance(raw_response, dict):
                    raw_response = {
                        **raw_response,
                        "_routing": {
                            "task": self.task_name,
                            "provider": route.provider_name,
                            "model": self.last_model_name,
                        },
                    }
                return AIResponse(
                    content=response.content,
                    model=self.last_model_name,
                    token_used=response.token_used,
                    processing_time=response.processing_time,
                    raw_response=raw_response,
                )
            except Exception as exc:
                failures.append(f"{route.provider_name}:{route.model}:{exc}")
                logger.warning(
                    "LLM route failed task=%s provider=%s model=%s error=%s",
                    self.task_name,
                    route.provider_name,
                    route.model,
                    exc,
                )
        raise RuntimeError(
            f"All LLM routes failed for task '{self.task_name}'. Attempts: {' | '.join(failures)}"
        )

    def health_check(self):
        route = self.routes[0]
        provider = self._build_provider(route)
        health = provider.health_check()
        if isinstance(health, dict):
            health.setdefault("service", route.provider_name)
            health.setdefault("model", route.model)
            health["task"] = self.task_name
        return health

    def _build_provider(self, route: ProviderRoute) -> BaseAIProvider:
        provider_cls = PROVIDER_CLASS_MAP[route.provider_name]
        return provider_cls(
            model=route.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            stream=self.stream,
        )


class LLMRouter:
    def provider_for(
        self,
        *,
        task_name: str,
        provider_name: str | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        stream: bool = False,
    ) -> RoutedAIProvider:
        return RoutedAIProvider(
            task_name=task_name,
            provider_name=provider_name,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream,
        )

    def health_check(self, *, task_name: str = "current_situation") -> dict:
        provider = self.provider_for(task_name=task_name, temperature=0.0)
        health = provider.health_check()
        if isinstance(health, dict):
            health["provider"] = provider.last_provider_name
            health["model"] = provider.last_model_name
        return health


def get_default_router() -> LLMRouter:
    return LLMRouter()


def create_routed_provider(
    *,
    task_name: str,
    provider_name: str | None = None,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    stream: bool = False,
) -> RoutedAIProvider:
    return get_default_router().provider_for(
        task_name=task_name,
        provider_name=provider_name,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=stream,
    )
