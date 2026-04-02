from __future__ import annotations

from dataclasses import dataclass

from ai.providers.base import AIResponse, BaseAIProvider
from ai.providers.router import create_routed_provider

TIMELINE_INSIGHT_PROVIDER_OLLAMA = "ollama"


@dataclass
class TimelineAIProviderAdapter:
    provider: BaseAIProvider

    def generate_timeline_insight(
        self,
        *,
        prompt: str,
        system_prompt: str | None = None,
    ) -> AIResponse:
        return self.provider.generate_response(prompt=prompt, system_prompt=system_prompt)


class OllamaTimelineAIProviderAdapter(TimelineAIProviderAdapter):
    pass


def get_timeline_ai_provider_adapter(
    *,
    provider_name: str | None = None,
    model: str | None = None,
    temperature: float = 0.1,
    max_tokens: int | None = 700,
) -> TimelineAIProviderAdapter:
    return OllamaTimelineAIProviderAdapter(
        provider=create_routed_provider(
            task_name="timeline_insight",
            provider_name=provider_name,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    )
