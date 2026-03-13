from __future__ import annotations

import json
import re
from typing import Any

from ai.config import get_missing_ai_env_vars, get_ollama_model
from ai.providers.ollama_provider import OllamaProvider


class GIEGoalLanguageRefinementService:
    """Refines goal copy while preserving user intent."""

    _FILLER_PATTERN = re.compile(
        r"\b(um+|uh+|like|you know|kind of|sort of|actually|basically|i mean)\b",
        re.IGNORECASE,
    )

    @classmethod
    def refine_autofill_payload(cls, *, payload: dict[str, Any], raw_goal: str) -> dict[str, Any]:
        refined = cls._basic_refine(payload=payload)
        if get_missing_ai_env_vars():
            return refined

        try:
            provider = OllamaProvider(model=get_ollama_model(), temperature=0.2, max_tokens=600)
            prompt = cls._build_prompt(payload=refined, raw_goal=raw_goal)
            response = provider.generate_response(
                prompt=prompt,
                system_prompt=(
                    "You are a goal-writing editor. Improve clarity and motivation while preserving user intent. "
                    "Do not invent facts. Return valid JSON only."
                ),
            )
            parsed = json.loads(response.content)
            if not isinstance(parsed, dict):
                return refined

            next_payload = dict(refined)
            for key in ("title", "description", "why_do_i_want_this"):
                value = parsed.get(key)
                if isinstance(value, str) and value.strip():
                    next_payload[key] = value.strip()
            return next_payload
        except Exception:
            return refined

    @classmethod
    def _basic_refine(cls, *, payload: dict[str, Any]) -> dict[str, Any]:
        refined = dict(payload)
        refined["title"] = cls._clean_title(str(payload.get("title") or ""))
        refined["description"] = cls._clean_sentence_block(str(payload.get("description") or ""))
        refined["why_do_i_want_this"] = cls._clean_why_block(str(payload.get("why_do_i_want_this") or ""))
        return refined

    @classmethod
    def _clean_title(cls, text: str) -> str:
        text = cls._normalize_ws(text)
        if not text:
            return text
        return text[:1].upper() + text[1:]

    @classmethod
    def _clean_sentence_block(cls, text: str) -> str:
        cleaned = cls._normalize_ws(cls._FILLER_PATTERN.sub("", text))
        if not cleaned:
            return cleaned
        return cleaned[:1].upper() + cleaned[1:]

    @classmethod
    def _clean_why_block(cls, text: str) -> str:
        cleaned = cls._clean_sentence_block(text)
        if not cleaned:
            return cleaned
        if not cleaned.lower().startswith("i "):
            cleaned = f"I want this because {cleaned[:1].lower() + cleaned[1:]}"
        if not any(token in cleaned.lower() for token in ("because", "so that", "to ")):
            cleaned = f"{cleaned} so I can build meaningful long-term progress."
        return cleaned

    @staticmethod
    def _normalize_ws(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _build_prompt(*, payload: dict[str, Any], raw_goal: str) -> str:
        return (
            "Refine the following goal fields into clear, polished English for a non-fluent speaker.\n"
            "Preserve meaning. Do not add new facts.\n"
            "Use motivating but realistic wording.\n\n"
            f"Raw user goal: {raw_goal}\n"
            f"Title: {payload.get('title', '')}\n"
            f"Description: {payload.get('description', '')}\n"
            f"Why do I want this: {payload.get('why_do_i_want_this', '')}\n\n"
            "Return ONLY JSON with keys: title, description, why_do_i_want_this."
        )
