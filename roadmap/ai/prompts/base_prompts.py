# roadmap/ai/prompts/base_prompts.py

from typing import Dict, Any


class BasePrompt:
    """
    Base class for all prompts.
    Supports optional variables, defaults, and safe formatting.
    """

    def __init__(self):
        self.template: str = ""
        self.required_variables: list[str] = []
        self.default_variables: Dict[str, Any] = {}

    def format(self, strict: bool = False, **kwargs) -> str:
        """
        Format prompt with provided variables.

        Args:
            strict: If True, missing required variables raise error
            **kwargs: Variables to insert into template

        Returns:
            Formatted prompt string
        """

        # Merge defaults with provided values
        context = {**self.default_variables, **kwargs}

        if strict:
            missing = [
                var for var in self.required_variables if var not in context
            ]
            if missing:
                raise ValueError(
                    f"Missing required variables for prompt: {', '.join(missing)}"
                )

        try:
            return self.template.format(**context)
        except KeyError as e:
            raise ValueError(f"Prompt formatting error: missing variable {e}")

    def validate_context(self, context: Dict[str, Any]) -> bool:
        """Check if required variables exist (non-strict)"""
        return all(var in context for var in self.required_variables)


class StructuredOutputPrompt(BasePrompt):
    """
    Prompt that enforces structured JSON output.
    """

    def __init__(self, output_schema: dict):
        super().__init__()
        self.output_schema = output_schema

    def format(self, strict: bool = False, **kwargs) -> str:
        base_prompt = super().format(strict=strict, **kwargs)

        schema_instruction = f"""
IMPORTANT:
- Respond ONLY with valid JSON
- Match this schema exactly
- No explanations, no markdown

Schema:
{self._format_schema()}
"""
        return f"{base_prompt.strip()}\n\n{schema_instruction.strip()}"

    def _format_schema(self) -> str:
        import json
        return json.dumps(self.output_schema, indent=2)
